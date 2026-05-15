"""DynamoDB-backed QuotaStore — Phase 2 impl of the protocol in cricdata_poller.

Same semantics as SqliteQuotaStore. Keeps the poller call site identical;
the fail-closed threshold lives in cricdata_poller and is not duplicated here.
"""

from __future__ import annotations

from typing import Any


class DynamoQuotaStore:
    def __init__(self, ddb_resource: Any, table_name: str):
        self.table = ddb_resource.Table(table_name)

    def get(self, day: str) -> int:
        resp = self.table.get_item(Key={"date": day}, ConsistentRead=True)
        item = resp.get("Item")
        return int(item["hits"]) if item else 0

    def increment(self, day: str) -> int:
        resp = self.table.update_item(
            Key={"date": day},
            UpdateExpression="ADD hits :one",
            ExpressionAttributeValues={":one": 1},
            ReturnValues="UPDATED_NEW",
        )
        return int(resp["Attributes"]["hits"])
