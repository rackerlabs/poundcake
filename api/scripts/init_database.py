#!/usr/bin/env python3
"""Initialize simplified PoundCake database - just 3 tables!

This is MUCH simpler than the complex architecture.
We're just a thin tracking layer over StackStorm.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from api.core.database import engine, Base
from sqlalchemy import inspect, create_engine
import os


def check_st2_database() -> tuple[bool, list[str]]:
    """Check if StackStorm database exists."""
    print("\n📊 Checking StackStorm Database...")

    st2_db_url = os.getenv(
        "ST2_DATABASE_URL", "mysql+pymysql://stackstorm:stackstorm@localhost:3306/stackstorm"
    )

    try:
        st2_engine = create_engine(st2_db_url)
        st2_inspector = inspect(st2_engine)
        st2_tables = st2_inspector.get_table_names()

        expected_tables = ["action_db", "execution_db", "rule_db"]
        found_tables = [t for t in expected_tables if t in st2_tables]

        if found_tables:
            print(f"  ✓ Found StackStorm tables: {', '.join(found_tables)}")
            print(f"  ✓ Total ST2 tables: {len(st2_tables)}")
            return True, st2_tables
        else:
            print("  ⚠ StackStorm tables not found")
            return False, []
    except Exception as e:
        print(f"  ℹ Cannot connect to StackStorm database: {e}")
        return False, []


def create_poundcake_tables() -> list[str]:
    """Create PoundCake tables - just 3!"""
    print("\n🔨 Creating PoundCake Tables...")

    existing = inspect(engine).get_table_names()

    # Create all tables
    Base.metadata.create_all(bind=engine)

    new_tables = set(inspect(engine).get_table_names()) - set(existing)

    if new_tables:
        print(f"  ✓ Created {len(new_tables)} tables:")
        for table in sorted(new_tables):
            print(f"    - {table}")
    else:
        print("  - Tables already exist")

    return list(new_tables)


def show_simplified_architecture() -> None:
    """Show the simplified architecture."""
    print("\n" + "=" * 70)
    print("SIMPLIFIED ARCHITECTURE")
    print("=" * 70)
    print("""
┌────────────────────────────────────────────────┐
│          MariaDB Database                      │
├────────────────────────────────────────────────┤
│                                                │
│ PoundCake Tables (ONLY 3):                    │
│   ✓ poundcake_api_calls      (request_id)    │
│   ✓ poundcake_alerts          (alert data)    │
│   ✓ poundcake_st2_execution_link (THE KEY!)  │
│                                                │
│ StackStorm Tables (ST2 manages):              │
│   ✓ action_db                 (actions)       │
│   ✓ execution_db              (executions)    │
│   ✓ rule_db                   (rules)         │
│   ✓ workflow_db               (workflows)     │
└────────────────────────────────────────────────┘

PoundCake's Job:
  1. Receive webhooks
  2. Generate request_id
  3. Store alert data
  4. Trigger StackStorm (pass request_id)
  5. Track link: request_id ↔ st2_execution_id

StackStorm's Job:
  1. Define workflows (ActionChains, Mistral, Orquesta)
  2. Define actions (python, shell, http, etc.)
  3. Execute remediation
  4. Store results

NO MORE:
  ❌ actions table
  ❌ custom_action_buckets table
  ❌ custom_action_bucket_steps table
  ❌ Complex extension tables

MUCH SIMPLER!
""")


def show_example_queries() -> None:
    """Show example queries for the simplified architecture."""
    print("\n" + "=" * 70)
    print("EXAMPLE QUERIES")
    print("=" * 70)

    queries = [
        (
            "Get complete remediation history",
            """
SELECT 
    api.request_id,
    alert.alert_name,
    alert.severity,
    link.st2_execution_id,
    exec.action as st2_workflow,
    exec.status
FROM poundcake_api_calls api
JOIN poundcake_alerts alert ON alert.api_call_id = api.id
LEFT JOIN poundcake_st2_execution_link link ON link.alert_id = alert.id
LEFT JOIN execution_db exec ON exec.id = link.st2_execution_id
WHERE api.request_id = 'your-request-id';
        """,
        ),
        (
            "Get workflow success rates",
            """
SELECT 
    exec.action as workflow,
    COUNT(*) as total,
    SUM(CASE WHEN exec.status = 'succeeded' THEN 1 ELSE 0 END) as succeeded
FROM execution_db exec
JOIN poundcake_st2_execution_link link ON exec.id = link.st2_execution_id
GROUP BY exec.action;
        """,
        ),
        (
            "Get all executions for an alert",
            """
SELECT 
    alert.alert_name,
    api.request_id,
    link.st2_execution_id,
    exec.action,
    exec.status
FROM poundcake_alerts alert
JOIN poundcake_api_calls api ON alert.api_call_id = api.id
LEFT JOIN poundcake_st2_execution_link link ON link.alert_id = alert.id
LEFT JOIN execution_db exec ON exec.id = link.st2_execution_id
WHERE alert.fingerprint = 'your-fingerprint';
        """,
        ),
    ]

    for title, query in queries:
        print(f"\n{title}:")
        print(query)


def main() -> None:
    """Main initialization function."""
    print("=" * 70)
    print("PoundCake Simplified Database Initialization")
    print("=" * 70)

    # Check StackStorm
    st2_exists, st2_tables = check_st2_database()

    if not st2_exists:
        print("\n⚠ StackStorm database not found")
        print("   PoundCake tables will be created anyway.")
        print("   Install StackStorm for full integration.")
        print("\n   See: docs/STACKSTORM_MARIADB_INSTALL.md")
        response = input("\nContinue? (y/n): ")
        if response.lower() != "y":
            sys.exit(1)

    # Create PoundCake tables
    create_poundcake_tables()

    # Show architecture
    show_simplified_architecture()

    # Show example queries
    show_example_queries()

    # Summary
    print("\n" + "=" * 70)
    print("✅ Initialization Complete!")
    print("=" * 70)

    print("\nPoundCake Tables Created:")
    print("  ✓ poundcake_api_calls       - Webhook tracking")
    print("  ✓ poundcake_alerts           - Alert data")
    print("  ✓ poundcake_st2_execution_link - Links to ST2")

    if st2_exists:
        print("\nStackStorm Integration:")
        print("  ✓ StackStorm database detected")
        print("  ✓ Ready for unified deployment")
    else:
        print("\nStackStorm Not Detected:")
        print("  ℹ Install StackStorm with MariaDB")
        print("  ℹ Then restart PoundCake services")

    print("\nNext Steps:")
    print("  1. Install/Configure StackStorm (if not done)")
    print("  2. Create ST2 workflows in /opt/stackstorm/packs/")
    print("  3. Register workflows: st2 action create workflow.yaml")
    print("  4. Create ST2 rules to match alerts")
    print("  5. Start PoundCake: docker-compose up -d")
    print("  6. Test: ./test-webhook.sh")

    print("\nCreate StackStorm Workflow Example:")
    print("  # Create workflow YAML")
    print("  vi /opt/stackstorm/packs/remediation/actions/workflows/host_down.yaml")
    print("  ")
    print("  # Register with ST2")
    print("  st2 action create host_down.yaml")
    print("  ")
    print("  # Test")
    print("  st2 run remediation.host_down_workflow \\")
    print("    instance=server-01 poundcake_request_id=test-123")

    print("\nSee docs/SIMPLE_ARCHITECTURE.md for complete guide!")
    print()


if __name__ == "__main__":
    main()
