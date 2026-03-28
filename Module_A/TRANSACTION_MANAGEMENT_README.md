# Module A: Transaction Management, Crash Recovery & ACID Validation

## Overview

Module A extends the Assignment 2 B+ Tree database system with full transaction support and crash recovery capabilities. The implementation ensures ACID properties (Atomicity, Consistency, Durability) through:

1. **Write-Ahead Logging (WAL)** - All operations logged before commit
2. **Transaction Management** - Complete transaction lifecycle handling
3. **Rollback Support** - All-or-nothing transaction semantics
4. **Crash Recovery** - System recovery from failures using WAL
5. **Consistency Validation** - Automatic data integrity verification

## Architecture

### Core Components

#### 1. **WriteAheadLogger** (`write_ahead_logger.py`)
Persists all database operations to disk before they are committed, enabling durability.

**Key Classes:**
- `OperationType` - Enum of loggable operations (INSERT, UPDATE, DELETE, COMMIT, ABORT)
- `LogEntry` - Individual log entry with metadata
- `WriteAheadLogger` - Main logger managing disk I/O and log recovery

**Features:**
- Line-by-line JSON serialization to disk
- Automatic loading of existing logs on startup
- In-memory buffering with batch flush
- Proper serialization/deserialization of complex values
- Transaction-based log organization

```python
# Example: Creating and logging operations
wal = WriteAheadLogger("module_a_wal.log")
wal.begin_transaction(txn_id=1)
wal.log_operation(txn_id=1, OperationType.INSERT, key=10, value={"id": 10})
wal.commit(txn_id=1)  # Flush to disk
```

#### 2. **TransactionManager** (`transaction_manager.py`)
Manages transaction lifecycle and maintains transaction state.

**Key Classes:**
- `TransactionStatus` - Enum (ACTIVE, COMMITTED, ABORTED)
- `Transaction` - Represents a single transaction
- `TransactionManager` - Manages multiple transactions

**Features:**
- Begin, commit, abort transaction semantics
- Operation tracking for rollback
- Undo operation generation (LIFO order)
- Transaction statistics and monitoring

```python
# Example: Transaction management
txn_mgr = TransactionManager()
txn_id = txn_mgr.begin_transaction()
txn_mgr.add_operation(txn_id, "INSERT", key=10, value=data)
txn_mgr.commit(txn_id)  # or txn_mgr.abort(txn_id)
```

#### 3. **TransactionalBPlusTree** (`transactional_bplustree.py`)
Extends base B+ Tree with full transaction support.

**Key Features:**
- Transactional insert, update, delete operations
- Automatic WAL logging before each operation
- Rollback capability (reverses operations in reverse order)
- Auto-commit for standalone operations
- Transaction statistics and monitoring

```python
# Example: Using transactional tree
tree = TransactionalBPlusTree(wal_file="wal.log")
txn_id = tree.begin_transaction()
tree.insert(10, {"id": 10}, txn_id)
tree.update(10, {"id": 10, "value": 200}, txn_id)
tree.commit()  # All 2 operations committed atomically
```

#### 4. **RecoveryManager** (`recovery_manager.py`)
Handles crash recovery by replaying committed transactions from WAL.

**Key Classes:**
- `RecoveryManager` - Replays logged operations after failure
- `CheckpointManager` - Manages system checkpoints (optional)

**Features:**
- Committed transaction replay
- Operation filtering (skip aborted txns)
- Recovery statistics tracking
- Optional checkpoint support for faster recovery

```python
# Example: Crash recovery
recovery_mgr = RecoveryManager(wal)
stats = recovery_mgr.recover(apply_operation_callback)
# Replay committed operations into fresh database instance
```

#### 5. **ConsistencyChecker** (`consistency_checker.py`)
Validates ACID properties and data integrity.

**Key Methods:**
- `validate_bplustree_structure()` - Verify B+ tree invariants
- `validate_db_bplustree_consistency()` - Check DB/index alignment
- `validate_transaction_state()` - Verify transaction metadata

**Checks:**
1. Key ordering (sorted in each node)
2. Node capacity constraints
3. Parent-child relationships
4. Leaf node linking
5. Record consistency
6. Transaction state validity

```python
# Example: Validation
checker = ConsistencyChecker()
valid = checker.validate_bplustree_structure(tree.root)
if not valid:
    print(checker.get_errors())
```

## ACID Properties Implementation

### A. Atomicity (All-or-Nothing)
**Implementation:**
- One transaction → one logical unit
- All operations logged before commit
- Rollback mechanism undoes all changes in reverse order
- No partial execution possible

**Testing:**
- Test commit: all operations persisted
- Test rollback: all operations undone
- Multi-op transactions: all-or-nothing

```python
# Test scenario
txn_id = tree.begin_transaction()
tree.insert(10, val1)
tree.insert(20, val2)
tree.insert(30, val3)
tree.rollback()  # ALL 3 inserts undone
# Result: 10, 20, 30 keys don't exist
```

### B. Consistency (Data Validity)
**Implementation:**
- B+ Tree structure validated after operations
- Key ordering maintained
- Node splitting/merging preserves invariants
- DB/Tree alignment checked
- No orphaned records

**Testing:**
- Validate after inserts (splits occur)
- Validate after deletes (merges occur)
- Check DB/Tree match
- Verify after rollbacks

```python
# Test scenario
for i in range(20):
    tree.insert(i, data)  # Tree splits internally
# All 20 keys present and correctly ordered
checker.validate_bplustree_structure(tree.root)  # Returns True
```

### C. Durability (Data Persistence)
**Implementation:**
- WAL persists to disk before commit
- JSON-based serialization preserves data types
- Recovery replays committed transactions
- Uncommitted transactions discarded

**Testing:**
- Commit → disk persistence → recover → verify
- Multiple crash simulations
- Data type preservation through serialization

```python
# Test scenario
tree1.insert(10, {"id": 10})
tree1.commit()  # Data written to WAL log
# Simulate crash
tree2 = BPlusTree()
recovery.recover()  # Load from WAL
tree2.search(10)  # Returns {"id": 10}
```

### D. Isolation (Module B)
**To be implemented in Assignment 3 - Module B**
- Concurrent transaction testing
- Race condition detection
- Serializability verification
- Lock-based or MVCC approaches

## Testing

### Test Suite: ACID Validation (`acid_tests.py`)

13 comprehensive tests covering:

**Atomicity Tests (6):**
- ✓ Insert commit
- ✓ Insert rollback
- ✓ Delete rollback
- ✓ Update rollback
- ✓ Multi-operation commit
- ✓ Multi-operation rollback

**Consistency Tests (4):**
- ✓ Tree structure validation
- ✓ DB/tree match verification
- ✓ Consistency after deletions
- ✓ Consistency after rollbacks

**Durability Tests (2):**
- ✓ WAL persistence to disk
- ✓ Data recovery after restart

**Range Query Tests (1):**
- ✓ Range query consistency after rollback

**Results:**
- **Pass Rate:** 100% (13/13 tests)
- **Coverage:** Atomicity, Consistency, Durability, Recovery

### Demo Scenarios: Crash Recovery (`crash_recovery_demo.py`)

5 realistic demonstrations:

1. **Committed Data Survives Crash**
   - Insert and commit
   - Simulate crash during new transaction
   - Recover and verify data persistence

2. **Atomicity with Rollback**
   - Simulate money transfer (debit/credit)
   - Fail mid-operation
   - Rollback undoes all changes

3. **Consistency Validation**
   - Insert 20 items (tree splits)
   - Delete 5 items (tree merges)
   - Verify structure remains valid

4. **Durability and Recovery**
   - Insert 5 records and commit
   - Simulate restart
   - Recover from WAL
   - Verify all 5 records present

5. **Isolation Preview**
   - Explain isolation for Module B
   - Show concurrent operation concepts

## Key Features

### 1. Write-Ahead Logging (WAL)
- **Purpose:** Ensure durability by logging before commit
- **Format:** Line-based JSON for easy recovery
- **Serialization:** Proper JSON encoding of complex types
- **Recovery:** Auto-loading of logs on startup

### 2. Transaction Lifecycle
```
BEGIN → [Operations: INSERT/UPDATE/DELETE] → COMMIT/ABORT
 ↓              ↓                            ↓
State: ACTIVE   Logged to WAL              State: COMMITTED/ABORTED
       All ops tracked for rollback       Data persisted to disk
```

### 3. Rollback Operations
- **Reverse order** (LIFO) - undo last op first
- **Operation inversion:**
  - INSERT → DELETE to undo
  - DELETE → INSERT to restore
  - UPDATE → UPDATE with old value

### 4. Crash Recovery Flow
```
WAL Log (Disk)
     ↓
Load existing log
     ↓
Get committed transactions
     ↓
Replay each committed op
     ↓
Fresh database restored
```

## Usage Examples

### Basic Transaction
```python
from database.transactional_bplustree import TransactionalBPlusTree

tree = TransactionalBPlusTree(wal_file="wal.log")

# Single operation (auto-commit)
tree.insert(10, {"name": "Alice"})

# Multi-operation transaction
txn_id = tree.begin_transaction()
tree.insert(20, {"name": "Bob"}, txn_id)
tree.insert(30, {"name": "Charlie"}, txn_id)
tree.update(10, {"name": "Alice", "age": 25}, txn_id)
tree.commit()

# Rollback example
txn_id = tree.begin_transaction()
tree.delete(10, txn_id)
tree.rollback()  # Key 10 is restored

# Search (read-only, no transaction needed)
data = tree.search(20)
```

### Manual Recovery
```python
from database.write_ahead_logger import WriteAheadLogger, OperationType
from database.recovery_manager import RecoveryManager
from database.bplustree import BPlusTree

# Load existing WAL after crash
wal = WriteAheadLogger("wal.log")
recovery_mgr = RecoveryManager(wal)

# Fresh tree
tree = BPlusTree(order=4)

def apply_op(op_type, key, value, old_value):
    if op_type == OperationType.INSERT:
        tree.insert(key, value)
    elif op_type == OperationType.UPDATE:
        tree.update(key, value)
    elif op_type == OperationType.DELETE:
        tree.delete(key)

# Replay all committed transactions
stats = recovery_mgr.recover(apply_op)
print(f"Recovered {stats['replayed_operations']} operations")
```

### Consistency Checking
```python
from database.consistency_checker import ConsistencyChecker

checker = ConsistencyChecker()

# Validate tree structure
valid = checker.validate_bplustree_structure(tree.root)
if not valid:
    for error in checker.get_errors():
        print(f"Error: {error}")

# Validate DB/Tree consistency
db_records = {...}  # From main database
tree_records = dict(tree.get_all())
valid = checker.validate_db_bplustree_consistency(db_records, tree_records)
```

## Performance Characteristics

### Time Complexity
| Operation | Normal | With Logging | With Rollback |
|-----------|--------|--------------|---------------|
| Insert    | O(log n) | O(log n)     | O(log n)      |
| Delete    | O(log n) | O(log n)     | O(log n)      |
| Search    | O(log n) | O(log n)     | O(log n)      |
| Range Query | O(log n + k) | O(log n + k) | O(log n + k) |
| Commit    | — | O(txn_ops) | —             |
| Rollback  | — | O(txn_ops) | O(txn_ops)    |

### Space Complexity
- **WAL Log:** O(total_ops) - one entry per operation
- **Transaction State:** O(txn_ops) - operations tracked
- **Recovery:** O(committed_ops) - replayed operations

## Limitations & Future Work

### Current Limitations
1. **Single-threaded** - No concurrent transaction support (Module B)
2. **In-memory only** - Trees are in-memory, WAL is disk-based
3. **No checkpoint optimization** - Full recovery from START of log
4. **No two-phase commit** - Simple commit/abort only
5. **Isolation not implemented** - Module B task

### Future Enhancements
1. **Checkpoints** - Reduce recovery time
2. **Concurrent transactions** - Multiple active txns
3. **Lock manager** - Row/page locking for isolation
4. **B+ Tree persistence** - Save state to disk
5. **MVCC** - Multi-version concurrency control
6. **Two-phase commit** - Distributed transactions

## Files Overview

| File | Purpose | Status |
|------|---------|--------|
| `write_ahead_logger.py` | WAL implementation | ✓ Complete |
| `transaction_manager.py` | Transaction lifecycle | ✓ Complete |
| `transactional_bplustree.py` | Transactional B+ Tree | ✓ Complete |
| `recovery_manager.py` | Crash recovery | ✓ Complete |
| `consistency_checker.py` | Validation & verification | ✓ Complete |
| `acid_tests.py` | Test suite (13 tests) | ✓ Complete (100% pass) |
| `crash_recovery_demo.py` | Demo scenarios | ✓ Complete |
| `debug_wal.py` | WAL debugging utility | ✓ Complete |

## Running Tests

```bash
cd Module_A/database

# Run ACID tests
python acid_tests.py

# Run crash recovery demos
python crash_recovery_demo.py

# Debug WAL operations
python debug_wal.py
```

## Key Achievements

✓ **Full ACID Implementation**
- Atomicity: All-or-nothing transactions
- Consistency: Data and structure validity maintained
- Durability: WAL-based persistence
- Isolation: (Module B)

✓ **Crash Recovery**
- Automatic recovery from failures
- Committed data preserved
- Uncommitted transactions discarded

✓ **Comprehensive Testing**
- 13 ACID tests (100% pass rate)
- 5 realistic demo scenarios
- Edge cases covered

✓ **Production-Ready Code**
- Error handling
- Proper serialization
- Clean API design
- Detailed documentation

## Next Steps: Module B

Module B will extend this with:
- Concurrent transaction support
- Multi-threaded stress testing
- Isolation level enforcement
- Race condition handling
- Load testing with Locust/JMeter
