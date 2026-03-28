"""
Debug script to check WAL loading and recovery.
"""

import os
import tempfile
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from bplustree import BPlusTree
from transactional_bplustree import TransactionalBPlusTree
from write_ahead_logger import WriteAheadLogger, OperationType
from recovery_manager import RecoveryManager

# Create a temp file for WAL
temp_dir = tempfile.mkdtemp()
wal_file = os.path.join(temp_dir, "debug_wal.log")

print("="*70)
print("PHASE 1: INSERT AND COMMIT")
print("="*70)

tree1 = TransactionalBPlusTree(wal_file=wal_file)
print(f"Created tree1, WAL file: {wal_file}")
print(f"Tree1 WAL stats: {tree1.wal.get_log_statistics()}")

txn_id = tree1.begin_transaction()
print(f"\nBegun transaction {txn_id}")

tree1.insert(10, {"id": 10}, txn_id)
print(f"Inserted key 10")

tree1.commit()
print(f"Committed transaction {txn_id}")
print(f"Tree1 WAL stats after commit: {tree1.wal.get_log_statistics()}")

# Check WAL file contents
print(f"\nWAL file contents:")
with open(wal_file, 'r') as f:
    lines = f.readlines()
    for i, line in enumerate(lines):
        print(f"  {i}: {line.strip()}")

print("\n" + "="*70)
print("PHASE 2: LOAD WAL AND RECOVER")
print("="*70)

# Load existing WAL
print(f"\nLoading existing WAL from: {wal_file}")
wal2 = WriteAheadLogger(wal_file)
print(f"Loaded WAL stats: {wal2.get_log_statistics()}")
print(f"WAL entries in memory: {len(wal2.entries)}")

for i, entry in enumerate(wal2.entries):
    print(f"  Entry {i}: {entry}")

print(f"\nLooking for committed transactions...")
committed = wal2.get_committed_transactions()
print(f"Committed transactions: {committed.keys()}")

for txn_id, entries in committed.items():
    print(f"\nTransaction {txn_id}:")
    for entry in entries:
        print(f"  - {entry}")

print("\n" + "="*70)
print("RECOVERY TEST")
print("="*70)

tree2 = BPlusTree(order=4)
print(f"Created fresh tree2")

recovery_mgr = RecoveryManager(wal2)

def apply_op(op_type, key, value, old_value):
    print(f"Applying: op={op_type.value}, key={key}, value={value}")
    if op_type == OperationType.INSERT:
        tree2.insert(key, value)
    elif op_type == OperationType.DELETE:
        tree2.delete(key)
    elif op_type == OperationType.UPDATE:
        tree2.update(key, value)

print(f"\nStarting recovery...")
stats = recovery_mgr.recover(apply_op)
print(f"Recovery stats: {stats}")

print(f"\nVerifying recovered data:")
data = tree2.search(10)
print(f"tree2.search(10) = {data}")

if data == {"id": 10}:
    print("✓ SUCCESS: Data recovered correctly!")
else:
    print("✗ FAILED: Data not recovered")

# Cleanup
import shutil
shutil.rmtree(temp_dir)
