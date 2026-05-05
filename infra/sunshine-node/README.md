# Phase 1 — Sunshine on AWS, browser-verified

Provision an EC2 GPU instance in Mumbai (`ap-south-1`), install Sunshine + the moonlight-web WebRTC bridge, and verify a 1080p60 stream of `glxgears` from a browser. This recipe becomes the input to the Phase 4 orchestrator.

## Prerequisites

- AWS CLI configured and authenticated against the gaymr account.
  ```sh
  aws sts get-caller-identity   # should return your account
  ```
- Region default `ap-south-1`.
- G-instance vCPU quota approved in `ap-south-1` (otherwise `RunInstances` fails with `VcpuLimitExceeded`).
  ```sh
  aws service-quotas get-service-quota \
    --service-code ec2 --quota-code L-DB2E81BA --region ap-south-1
  # value should be >= 4 (for g4dn.xlarge)
  ```
- Keypair `gaymr-sunshine-mumbai` exists in `ap-south-1`; private key at `~/.ssh/gaymr-sunshine-mumbai.pem` (chmod 600).
- Desktop Moonlight installed locally for the §3 sanity check (`brew install --cask moonlight`).
- A modern Chrome on the laptop for the final browser verification.

## Cost guard

`g4dn.xlarge` on-demand: ~$0.526/hr. Step 1 budget: **≤4 hours wall time, ~$2 total**. Set a calendar reminder. The instance has `--instance-initiated-shutdown-behavior terminate`, so a `sudo shutdown -h now` from inside also tears the EBS volume down.

## Run sequence

```sh
cd infra/sunshine-node

# 1. Launch the instance + security group locked to your public IP.
./launch.sh
# → prints a public IP, writes .last-public-ip and .last-instance-id

# 2. Wait ~60s for SSH, then provision (idempotent, ~3-5 min).
./provision-remote.sh
# → installs Xorg + NVIDIA driver config + Sunshine + moonlight-web

# 3. (One-time) open the Sunshine admin UI to set credentials.
ssh -i ~/.ssh/gaymr-sunshine-mumbai.pem \
  -L 47990:localhost:47990 \
  ubuntu@$(cat .last-public-ip)
# Then in your browser: https://localhost:47990
#   - Set admin user/pass on first load.
#   - Add a "glxgears" application: cmd = /usr/bin/glxgears, env DISPLAY=:0.

# 4. Sanity-check with desktop Moonlight (do this BEFORE the browser).
#    On your laptop, open Moonlight, "Add PC" → enter the public IP.
#    Sunshine displays a 4-digit PIN in its admin UI; enter it in Moonlight.
#    Launch the glxgears app. Expect smooth 60fps + mouse interaction.

# 5. Verify in the browser via moonlight-web.
#    https://<public-ip>:8443
#    Pair (same PIN flow) and launch glxgears.

# 6. Tear down (do this even if you're "just stepping away for lunch").
aws ec2 terminate-instances \
  --region ap-south-1 \
  --instance-ids $(cat .last-instance-id)
```

## Acceptance criteria

Step 1 is **done** when all of these are true:

- [ ] Chrome (latest) on the laptop loads moonlight-web over HTTPS, accepts the self-signed cert.
- [ ] glxgears renders at 1080p60 in the browser tab.
- [ ] `chrome://webrtc-internals` shows: H.264 video, RTT < 50 ms, framerate ≥ 55fps, packet loss < 1%.
- [ ] Mouse + keyboard input from the browser tab affects the gears.
- [ ] Stream survives 5 minutes without disconnect.
- [ ] On server: `nvidia-smi` shows `sunshine` process consuming the encoder.
- [ ] Killing Sunshine on the server triggers a clean disconnect in the browser within 5s.
- [ ] After `terminate-instances`, the AWS console shows the instance gone and the EBS volume released.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `VcpuLimitExceeded` on `launch.sh` | Quota still 0 | Wait for AWS approval; check `service-quotas get-service-quota`. |
| SSH hangs after `launch.sh` | Instance still booting / SG locked to wrong IP | `./launch.sh` reads your IP fresh each run; rerun the SG-creation block manually if your IP changed. |
| `provision.sh` fails at "Xorg did not come up with NVIDIA renderer" | BusID parser missed; or DLAMI driver mismatch | SSH in, run `nvidia-xconfig --query-gpu-info` manually, edit `/etc/X11/xorg.conf` with the literal BusID, restart Xorg. |
| Sunshine admin UI returns 502 / refuses connection | systemd unit not running | `sudo systemctl status sunshine`; check `/var/log/xorg-sunshine.log`. |
| Moonlight pairs but stream is black | NVENC failed to initialize | Check Sunshine log for `nvenc init failed`; usually fixed by restarting Xorg + Sunshine after the BusID is correct. |
| moonlight-web Docker image 404 | Repo path changed | See [games-on-whales/moonlight-web](https://github.com/games-on-whales/moonlight-web) for current image; override with `MOONLIGHT_WEB_IMAGE=...` env var. If unfixable, complete §4 (desktop Moonlight) and proceed — Phase 2 builds our own WebRTC server anyway. |
| Browser stream is 720p, not 1080p | moonlight-web client negotiated lower res | Set resolution in moonlight-web settings; verify `sunshine.conf` resolutions list. |
| Stream stutters every few seconds | Bufferbloat on the upstream link | Check fast.com **loaded latency**; if >100 ms, your local network is the bottleneck, not AWS. |
| Instance terminates unexpectedly | `--instance-initiated-shutdown-behavior terminate` triggered by an in-VM shutdown | Expected behaviour. Re-launch. |

## What this recipe leaves behind

- A working procedure that we re-run via SSM Run Command in Phase 4 (orchestrator).
- Confidence that the Mumbai → Bengaluru network path supports our latency budget.
- A documented driver/AMI version pin (the AMI ID is captured in `launch.sh`'s call to SSM).

## What this recipe does *not* do (deferred to Phase 2)

- Custom WebRTC server (we use moonlight-web here as a stand-in).
- Programmatic pairing (we PIN-pair manually here).
- Game launch automation (Sunshine config has glxgears hard-coded).
- Idempotent re-provisioning of the *same* node across multiple sessions (each Phase 1 run is one-shot).
