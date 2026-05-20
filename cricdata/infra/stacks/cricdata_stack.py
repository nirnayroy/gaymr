"""cricdata Phase 2 stack: S3 + Lambda + Glue + Athena + DynamoDB (quota).

Live polling schedule is created **disabled**. Turning it on is Phase 3,
gated by a manual quota-guard fault-injection test (PHASE2.md, verification step 4).
"""

from __future__ import annotations

from pathlib import Path

import aws_cdk as cdk
from aws_cdk import (
    aws_athena as athena,
    aws_cloudwatch as cloudwatch,
    aws_cloudwatch_actions as cw_actions,
    aws_dynamodb as dynamodb,
    aws_events as events,
    aws_events_targets as targets,
    aws_glue as glue,
    aws_iam as iam,
    aws_lambda as _lambda,
    aws_s3 as s3,
    aws_s3_notifications as s3n,
    aws_sns as sns,
    aws_sns_subscriptions as subs,
    aws_ssm as ssm,
)
from constructs import Construct

ALERT_EMAIL = "nroy1012@gmail.com"
METRIC_NAMESPACE = "cricdata"

CRICDATA_ROOT = Path(__file__).resolve().parents[2]


class CricdataStack(cdk.Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        account = self.account

        # --- S3 buckets -------------------------------------------------
        raw = s3.Bucket(
            self, "RawBucket",
            bucket_name=f"gaymr-cricdata-raw-{account}",
            versioned=True,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            lifecycle_rules=[
                s3.LifecycleRule(
                    transitions=[
                        s3.Transition(storage_class=s3.StorageClass.INFREQUENT_ACCESS,
                                      transition_after=cdk.Duration.days(30)),
                        s3.Transition(storage_class=s3.StorageClass.GLACIER,
                                      transition_after=cdk.Duration.days(180)),
                    ],
                )
            ],
            removal_policy=cdk.RemovalPolicy.RETAIN,
        )

        curated = s3.Bucket(
            self, "CuratedBucket",
            bucket_name=f"gaymr-cricdata-curated-{account}",
            versioned=False,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            removal_policy=cdk.RemovalPolicy.RETAIN,
        )

        athena_results = s3.Bucket(
            self, "AthenaResultsBucket",
            bucket_name=f"gaymr-cricdata-athena-{account}",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            lifecycle_rules=[s3.LifecycleRule(expiration=cdk.Duration.days(30))],
            removal_policy=cdk.RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )

        # --- DynamoDB quota table (api_quota) ---------------------------
        quota_table = dynamodb.Table(
            self, "QuotaTable",
            table_name="cricdata_api_quota",
            partition_key=dynamodb.Attribute(name="date", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            time_to_live_attribute="ttl",
            removal_policy=cdk.RemovalPolicy.RETAIN,
        )

        # --- Glue catalog ----------------------------------------------
        glue_db = glue.CfnDatabase(
            self, "GlueDb",
            catalog_id=account,
            database_input=glue.CfnDatabase.DatabaseInputProperty(name="cricdata"),
        )

        common_storage = {
            "input_format": "org.apache.hadoop.hive.ql.io.parquet.MapredParquetInputFormat",
            "output_format": "org.apache.hadoop.hive.ql.io.parquet.MapredParquetOutputFormat",
            "serde_info": glue.CfnTable.SerdeInfoProperty(
                serialization_library="org.apache.hadoop.hive.ql.io.parquet.serde.ParquetHiveSerDe"
            ),
        }

        matches_table = glue.CfnTable(
            self, "MatchesTable",
            catalog_id=account,
            database_name="cricdata",
            table_input=glue.CfnTable.TableInputProperty(
                name="matches",
                table_type="EXTERNAL_TABLE",
                parameters={"classification": "parquet"},
                partition_keys=[
                    glue.CfnTable.ColumnProperty(name="year", type="int"),
                    glue.CfnTable.ColumnProperty(name="format", type="string"),
                ],
                storage_descriptor=glue.CfnTable.StorageDescriptorProperty(
                    location=f"s3://{curated.bucket_name}/curated/matches/",
                    columns=[
                        glue.CfnTable.ColumnProperty(name="match_id", type="string"),
                        glue.CfnTable.ColumnProperty(name="date", type="string"),
                        glue.CfnTable.ColumnProperty(name="venue", type="string"),
                        glue.CfnTable.ColumnProperty(name="team_home", type="string"),
                        glue.CfnTable.ColumnProperty(name="team_away", type="string"),
                        glue.CfnTable.ColumnProperty(name="winner", type="string"),
                    ],
                    **common_storage,
                ),
            ),
        )
        matches_table.add_dependency(glue_db)

        deliveries_table = glue.CfnTable(
            self, "DeliveriesTable",
            catalog_id=account,
            database_name="cricdata",
            table_input=glue.CfnTable.TableInputProperty(
                name="deliveries",
                table_type="EXTERNAL_TABLE",
                parameters={"classification": "parquet"},
                partition_keys=[
                    glue.CfnTable.ColumnProperty(name="year", type="int"),
                    glue.CfnTable.ColumnProperty(name="format", type="string"),
                ],
                storage_descriptor=glue.CfnTable.StorageDescriptorProperty(
                    location=f"s3://{curated.bucket_name}/curated/deliveries/",
                    columns=[
                        glue.CfnTable.ColumnProperty(name="match_id", type="string"),
                        glue.CfnTable.ColumnProperty(name="innings", type="int"),
                        glue.CfnTable.ColumnProperty(name="over", type="int"),
                        glue.CfnTable.ColumnProperty(name="ball", type="int"),
                        glue.CfnTable.ColumnProperty(name="batter", type="string"),
                        glue.CfnTable.ColumnProperty(name="bowler", type="string"),
                        glue.CfnTable.ColumnProperty(name="non_striker", type="string"),
                        glue.CfnTable.ColumnProperty(name="runs_batter", type="int"),
                        glue.CfnTable.ColumnProperty(name="runs_extras", type="int"),
                        glue.CfnTable.ColumnProperty(name="runs_total", type="int"),
                        glue.CfnTable.ColumnProperty(name="wicket_kind", type="string"),
                        glue.CfnTable.ColumnProperty(name="player_out", type="string"),
                    ],
                    **common_storage,
                ),
            ),
        )
        deliveries_table.add_dependency(glue_db)

        # --- Athena workgroup with 1GB scan cap -------------------------
        athena.CfnWorkGroup(
            self, "AthenaWg",
            name="cricdata",
            work_group_configuration=athena.CfnWorkGroup.WorkGroupConfigurationProperty(
                result_configuration=athena.CfnWorkGroup.ResultConfigurationProperty(
                    output_location=f"s3://{athena_results.bucket_name}/results/"
                ),
                bytes_scanned_cutoff_per_query=1_000_000_000,  # 1 GB
                enforce_work_group_configuration=True,
                publish_cloud_watch_metrics_enabled=True,
            ),
        )

        # --- Lambdas ----------------------------------------------------
        lambda_code = _lambda.Code.from_asset(str(CRICDATA_ROOT.parent))

        etl_fn = _lambda.Function(
            self, "CricsheetEtlFn",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="cricdata.lambdas.cricsheet_etl.handler",
            code=lambda_code,
            timeout=cdk.Duration.minutes(5),
            memory_size=1024,
            environment={
                "CURATED_BUCKET": curated.bucket_name,
                "CURATED_PREFIX": "curated",
            },
        )
        raw.grant_read(etl_fn)
        curated.grant_put(etl_fn)
        raw.add_event_notification(
            s3.EventType.OBJECT_CREATED,
            s3n.LambdaDestination(etl_fn),
            s3.NotificationKeyFilter(prefix="raw/cricsheet/", suffix=".zip"),
        )

        api_key_param = ssm.StringParameter(
            self, "CricdataApiKey",
            parameter_name="/cricdata/api_key",
            string_value="REPLACE_ME_AFTER_DEPLOY",
            description="CricketData.org API key — overwrite via aws ssm put-parameter after deploy",
        )

        poller_fn = _lambda.Function(
            self, "CricdataPollerFn",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="cricdata.lambdas.cricdata_poller_lambda.handler",
            code=lambda_code,
            timeout=cdk.Duration.seconds(30),
            memory_size=256,
            environment={
                "CRICDATA_API_KEY_PARAM": api_key_param.parameter_name,
                "QUOTA_TABLE": quota_table.table_name,
                "RAW_BUCKET": raw.bucket_name,
                "RAW_PREFIX": "raw/cricdata",
                "METRIC_NAMESPACE": METRIC_NAMESPACE,
            },
        )
        api_key_param.grant_read(poller_fn)
        quota_table.grant_read_write_data(poller_fn)
        raw.grant_put(poller_fn)
        poller_fn.add_to_role_policy(iam.PolicyStatement(
            actions=["cloudwatch:PutMetricData"],
            resources=["*"],
            conditions={"StringEquals": {"cloudwatch:namespace": METRIC_NAMESPACE}},
        ))

        # --- Alerting ---------------------------------------------------
        alarm_topic = sns.Topic(self, "CricdataAlerts", display_name="cricdata alerts")
        alarm_topic.add_subscription(subs.EmailSubscription(ALERT_EMAIL))
        alarm_action = cw_actions.SnsAction(alarm_topic)

        # 1. Quota approaching limit (PutMetricData is per-invocation, alarm
        #    fires the moment the daily counter crosses 90).
        cloudwatch.Alarm(
            self, "QuotaHitsHigh",
            alarm_description="cricdata daily API hits >= 90 (limit 100, fail-closed at 95)",
            metric=cloudwatch.Metric(
                namespace=METRIC_NAMESPACE,
                metric_name="QuotaHits",
                statistic="Maximum",
                period=cdk.Duration.minutes(5),
            ),
            threshold=90,
            evaluation_periods=1,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        ).add_alarm_action(alarm_action)

        # 2. Any poller error (uncaught exception -> Lambda Errors metric)
        cloudwatch.Alarm(
            self, "PollerErrors",
            alarm_description="cricdata poller Lambda raised an unhandled exception",
            metric=poller_fn.metric_errors(period=cdk.Duration.minutes(5)),
            threshold=1,
            evaluation_periods=1,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_OR_EQUAL_TO_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        ).add_alarm_action(alarm_action)

        # 3. Quota guard firing repeatedly = schedule is too aggressive
        cloudwatch.Alarm(
            self, "QuotaExceededFrequent",
            alarm_description="cricdata quota guard rejected >5 calls in 24h — schedule too aggressive",
            metric=cloudwatch.Metric(
                namespace=METRIC_NAMESPACE,
                metric_name="QuotaExceeded",
                statistic="Sum",
                period=cdk.Duration.hours(24),
            ),
            threshold=5,
            evaluation_periods=1,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
        ).add_alarm_action(alarm_action)

        # Schedule created DISABLED — Phase 3 enables after fault-injection test
        events.Rule(
            self, "PollerSchedule",
            schedule=events.Schedule.rate(cdk.Duration.minutes(30)),
            enabled=False,
            targets=[targets.LambdaFunction(poller_fn)],
            description="DISABLED until Phase 3 quota-guard verification",
        )

        # --- Outputs ----------------------------------------------------
        cdk.CfnOutput(self, "RawBucketName", value=raw.bucket_name)
        cdk.CfnOutput(self, "CuratedBucketName", value=curated.bucket_name)
        cdk.CfnOutput(self, "QuotaTableName", value=quota_table.table_name)
        cdk.CfnOutput(self, "AthenaWorkgroup", value="cricdata")
        cdk.CfnOutput(self, "AlertTopicArn", value=alarm_topic.topic_arn)
        cdk.CfnOutput(self, "PollerFnName", value=poller_fn.function_name)
