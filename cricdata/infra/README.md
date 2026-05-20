# cricdata infra — Phase 2

Single CDK app pinned to **ap-south-1**, account **471824291894**.
See [../PHASE2.md](../PHASE2.md) for the full design + rationale.

## Pre-flight gates (do not skip)

1. Phase 1 spot-check green (closed by PR #2).
2. **AWS Budgets alert at $1/month** on the account. Set via console or:
   ```
   aws budgets create-budget --account-id 471824291894 \
     --budget file://budget.json --notifications-with-subscribers file://notify.json
   ```
3. `npm install -g aws-cdk` and `cdk bootstrap aws://471824291894/ap-south-1` (one-time).

## Setup (one-time, per developer)

```
python3 -m venv .venv
.venv/bin/pip install -e '.[dev,infra]'
cd cricdata/infra
cdk synth --app 'python3 app.py'
```

## Deploy

```
cd cricdata/infra
cdk deploy --app 'python3 app.py'
```

Outputs printed: `RawBucketName`, `CuratedBucketName`, `QuotaTableName`, `AthenaWorkgroup`.

## Post-deploy

1. Set the CricketData API key:
   ```
   aws ssm put-parameter --name /cricdata/api_key --type SecureString \
       --value '<key>' --overwrite
   ```
2. Verify the EventBridge poller schedule is **disabled** (it is by default):
   ```
   aws events describe-rule --name $(aws events list-rules --query 'Rules[?contains(Name,`Poller`)].Name' --output text)
   ```
3. Upload a single Cricsheet match ZIP:
   ```
   aws s3 cp ipl_one_match.zip s3://gaymr-cricdata-raw-471824291894/raw/cricsheet/
   ```
4. Athena smoke:
   ```
   aws athena start-query-execution \
     --work-group cricdata \
     --query-string 'SELECT COUNT(*) FROM cricdata.deliveries'
   ```

## Quota guard fault-injection (Phase 3 gate)

Before enabling the schedule, force-fault and confirm zero outbound HTTP:
```
aws dynamodb put-item --table-name cricdata_api_quota \
  --item '{"date": {"S": "'$(date -u +%F)'"}, "hits": {"N": "95"}}'
aws lambda invoke --function-name <PollerFnName> /tmp/out.json
cat /tmp/out.json   # expect {"status": "skipped", ...}
```
Then check CloudWatch logs for the poller — **no** outbound API call should appear.

## Phase 3 operations — turning on live polling

The schedule ships as `enabled=False`. Do **not** flip it on until every step
below has passed. See [../PHASE3.md](../PHASE3.md) and ADR 0006 for rationale.

### Order of operations
1. Deploy this stack (`cdk deploy`).
2. Confirm the **email subscription** to the `CricdataAlerts` SNS topic — AWS sends a confirmation link to `nroy1012@gmail.com`. Click it. Alarms do not deliver until confirmed.
3. Set the API key in SSM (see "Post-deploy" above).
4. Run the fault-injection test (above section).
5. Backfill historical IPL ZIP, confirm Athena queries.
6. Enable the schedule (below).
7. 24h soak — watch the `cricdata/QuotaHits` metric in CloudWatch.

### Enable / disable the schedule
```
# enable (one-time, after fault-injection passes)
aws events enable-rule --name $(aws events list-rules \
  --query 'Rules[?contains(Name,`Poller`)].Name' --output text)

# disable (one-line rollback)
aws events disable-rule --name $(aws events list-rules \
  --query 'Rules[?contains(Name,`Poller`)].Name' --output text)
```
After enabling, **also update CDK source** (`enabled=True`, `rate=...`) so the
next `cdk deploy` doesn't revert. Land that change in a separate PR.

### Starting cadence: every 4 hours
6 hits/day. 16x headroom under the 100/day cap. Tuned up only after a clean
24h soak. See ADR 0006.

### Alarms wired
- `QuotaHitsHigh` — fires when daily `cricdata/QuotaHits` >= 90.
- `PollerErrors` — fires on any unhandled Lambda exception.
- `QuotaExceededFrequent` — fires when the quota guard rejects >5 calls in 24h (schedule is too aggressive).

All three publish to the `CricdataAlerts` SNS topic.

## Destroy

```
cd cricdata/infra
cdk destroy --app 'python3 app.py'
```
`RawBucket` and `CuratedBucket` are RETAIN — `cdk destroy` will leave them.
Empty + delete manually if you really want them gone.
