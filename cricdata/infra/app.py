#!/usr/bin/env python3
"""CDK entry point for cricdata Phase 2.

Region pinned to ap-south-1 (Mumbai). Account from CDK_DEFAULT_ACCOUNT.
"""

from __future__ import annotations

import os

import aws_cdk as cdk

from cricdata.infra.stacks.cricdata_stack import CricdataStack

app = cdk.App()

CricdataStack(
    app,
    "CricdataStack",
    env=cdk.Environment(
        account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
        region="ap-south-1",
    ),
)

app.synth()
