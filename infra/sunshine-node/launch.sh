#!/usr/bin/env bash
# Launch a Sunshine GPU node on AWS EC2 (ap-south-1).
# Creates the security group on first run; reuses it after.
#
# Run from this directory:
#   ./launch.sh
#
# After the instance is up, ./provision-remote.sh copies the recipe across
# and runs it. This script only stands up the box.

set -euo pipefail
cd "$(dirname "$0")"

REGION="${REGION:-ap-south-1}"
INSTANCE_TYPE="${INSTANCE_TYPE:-g4dn.xlarge}"
KEYPAIR="${KEYPAIR:-gaymr-sunshine-mumbai}"
AMI_PARAM="/aws/service/deeplearning/ami/x86_64/base-oss-nvidia-driver-gpu-ubuntu-22.04/latest/ami-id"
NAME_TAG="${NAME_TAG:-gaymr-sunshine-step1}"
SG_NAME="${SG_NAME:-gaymr-sunshine-sg}"
# On-demand G/VT quota is 0 in ap-south-1; Spot quota is 4 vCPU. Default to spot
# for Phase 1. Set USE_SPOT=0 once on-demand quota is granted.
USE_SPOT="${USE_SPOT:-1}"

# ---------------------------------------------------------------------------
# Resolve the latest DLAMI Ubuntu 22.04 OSS NVIDIA AMI.
# ---------------------------------------------------------------------------
AMI_ID=$(aws ssm get-parameter --region "$REGION" --name "$AMI_PARAM" \
  --query 'Parameter.Value' --output text)
echo "[launch] AMI: $AMI_ID"

# ---------------------------------------------------------------------------
# Find or create the security group.
#
# Inbound:
#   22/tcp        SSH (your IP only)
#   47984/tcp     Sunshine HTTPS (clients)
#   47989/tcp     Sunshine RTSP
#   47990/tcp     Sunshine admin web UI
#   48010/tcp     Sunshine RTSP control
#   47998-48000/udp Sunshine video/audio/control (Moonlight)
#   48002-48010/udp Sunshine input + extra
#   8443/tcp      moonlight-web HTTPS
#   3478/udp      future TURN
#   49152-65535/udp WebRTC media (large range, locked to your IP)
# ---------------------------------------------------------------------------
SG_ID=$(aws ec2 describe-security-groups --region "$REGION" \
  --filters "Name=group-name,Values=${SG_NAME}" \
  --query 'SecurityGroups[0].GroupId' --output text 2>/dev/null || true)

MY_IP=$(curl -s https://checkip.amazonaws.com | tr -d '\n')
[ -n "$MY_IP" ] || { echo "Could not detect public IP"; exit 1; }
MY_CIDR="${MY_IP}/32"
echo "[launch] Locking inbound rules to ${MY_CIDR}"

if [ -z "$SG_ID" ] || [ "$SG_ID" = "None" ]; then
  SG_ID=$(aws ec2 create-security-group --region "$REGION" \
    --group-name "$SG_NAME" \
    --description "gaymr Sunshine + moonlight-web access" \
    --query 'GroupId' --output text)
  echo "[launch] Created SG $SG_ID"

  # SSH
  aws ec2 authorize-security-group-ingress --region "$REGION" --group-id "$SG_ID" \
    --protocol tcp --port 22 --cidr "$MY_CIDR" >/dev/null
  # Sunshine TCP
  for p in 47984 47989 47990 48010; do
    aws ec2 authorize-security-group-ingress --region "$REGION" --group-id "$SG_ID" \
      --protocol tcp --port "$p" --cidr "$MY_CIDR" >/dev/null
  done
  # Sunshine UDP
  aws ec2 authorize-security-group-ingress --region "$REGION" --group-id "$SG_ID" \
    --ip-permissions "IpProtocol=udp,FromPort=47998,ToPort=48010,IpRanges=[{CidrIp=${MY_CIDR}}]" >/dev/null
  # moonlight-web
  aws ec2 authorize-security-group-ingress --region "$REGION" --group-id "$SG_ID" \
    --protocol tcp --port 8443 --cidr "$MY_CIDR" >/dev/null
  # WebRTC media (host-network mode containers use ephemeral ports)
  aws ec2 authorize-security-group-ingress --region "$REGION" --group-id "$SG_ID" \
    --ip-permissions "IpProtocol=udp,FromPort=49152,ToPort=65535,IpRanges=[{CidrIp=${MY_CIDR}}]" >/dev/null
  # Future TURN
  aws ec2 authorize-security-group-ingress --region "$REGION" --group-id "$SG_ID" \
    --protocol udp --port 3478 --cidr "$MY_CIDR" >/dev/null
fi
echo "[launch] SG: $SG_ID"

# ---------------------------------------------------------------------------
# Launch.
# ---------------------------------------------------------------------------
RUN_ARGS=(
  --region "$REGION"
  --image-id "$AMI_ID"
  --instance-type "$INSTANCE_TYPE"
  --key-name "$KEYPAIR"
  --security-group-ids "$SG_ID"
  --block-device-mappings 'DeviceName=/dev/sda1,Ebs={VolumeSize=100,VolumeType=gp3,DeleteOnTermination=true}'
  --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=${NAME_TAG}},{Key=project,Value=gaymr},{Key=step,Value=1}]"
)
if [ "${USE_SPOT}" = "1" ]; then
  echo "[launch] Mode: SPOT (one-time, terminate on interruption)"
  RUN_ARGS+=(--instance-market-options 'MarketType=spot,SpotOptions={SpotInstanceType=one-time,InstanceInterruptionBehavior=terminate}')
else
  echo "[launch] Mode: ON-DEMAND"
  RUN_ARGS+=(--instance-initiated-shutdown-behavior terminate)
fi

INSTANCE_ID=$(aws ec2 run-instances "${RUN_ARGS[@]}" \
  --query 'Instances[0].InstanceId' --output text)

echo "[launch] Instance: $INSTANCE_ID"
echo "[launch] Waiting for instance to enter 'running'..."
aws ec2 wait instance-running --region "$REGION" --instance-ids "$INSTANCE_ID"

PUBLIC_IP=$(aws ec2 describe-instances --region "$REGION" --instance-ids "$INSTANCE_ID" \
  --query 'Reservations[0].Instances[0].PublicIpAddress' --output text)
echo "[launch] Public IP: $PUBLIC_IP"

cat <<EOF

[launch] Done. Instance is booting. SSH will be available in ~60s.

  ssh -i ~/.ssh/${KEYPAIR}.pem ubuntu@${PUBLIC_IP}

Next:
  ./provision-remote.sh ${PUBLIC_IP}

To terminate (and stop billing):
  aws ec2 terminate-instances --region ${REGION} --instance-ids ${INSTANCE_ID}

EOF

# Persist the active instance for downstream scripts.
echo "$INSTANCE_ID" > .last-instance-id
echo "$PUBLIC_IP"   > .last-public-ip
cat > .last-launch.env <<EOF
INSTANCE_ID=${INSTANCE_ID}
PUBLIC_IP=${PUBLIC_IP}
AMI_ID=${AMI_ID}
INSTANCE_TYPE=${INSTANCE_TYPE}
REGION=${REGION}
USE_SPOT=${USE_SPOT}
LAUNCHED_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ)
EOF
