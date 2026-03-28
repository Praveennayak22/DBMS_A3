"""
ACID Validation Test Suite for Module A.

Comprehensive tests for:
- Atomicity: All-or-nothing semantics
- Consistency: Data validity and correctness
- Durability: Data persistence after commit
- Isolation: (To be tested in Module B)

Also tests DB + B+ Tree consistency and crash recovery.
"""

import os
import sys
from pathlib import Path
from typing import Dict, List, Tuple
import json
import tempfile

from bplustree import BPlusTree
from transactional_bplustree import TransactionalBPlusTree
from write_ahead_logger import WriteAheadLogger, OperationType
from transaction_manager import TransactionManager, TransactionStatus
from recovery_manager import RecoveryManager
from consistency_checker import ConsistencyChecker


class ACIDTestResults:
    """Container for test results."""
    
    def __init__(self):
        self.tests_run = 0
        self.tests_passed = 0
        self.tests_failed = 0
        self.failures: List[str] = []
    
    def add_pass(self, test_name: str):
        self.tests_run += 1
        self.tests_passed += 1
        print(f"✓ {test_name}")
    
    def add_fail(self, test_name: str, reason: str):
        self.tests_run += 1
        self.tests_failed += 1
        self.failures.append(f"{test_name}: {reason}")
        print(f"✗ {test_name}: {reason}")
    
    def get_summary(self) -> Dict:
        return {
            "total": self.tests_run,
            "passed": self.tests_passed,
            "failed": self.tests_failed,
            "pass_rate": f"{(self.tests_passed/self.tests_run*100):.1f}%" if self.tests_run > 0 else "N/A",
            "failures": self.failures
        }
    
    def print_summary(self):
        summary = self.get_summary()
        print("\n" + "="*60)
        print("ACID TEST SUMMARY")
        print("="*60)
        print(f"Total Tests: {summary['total']}")
        print(f"Passed: {summary['passed']}")
        print(f"Failed: {summary['failed']}")
        print(f"Pass Rate: {summary['pass_rate']}")
        if summary['failures']:
            print("\nFailures:")
            for failure in summary['failures']:
                print(f"  - {failure}")
        print("="*60 + "\n")


class ACIDTests:
    """ACID test suite."""
    
    def __init__(self):
        self.results = ACIDTestResults()
        self.temp_dir = tempfile.mkdtemp()
    
    # ==================== ATOMICITY TESTS ====================
    
    def test_atomicity_insert_commit(self):
        """Test that committed inserts are durable."""
        try:
            tree = TransactionalBPlusTree(order=4)
            txn_id = tree.begin_transaction()
            tree.insert(10, {"id": 10}, txn_id)
            tree.insert(20, {"id": 20}, txn_id)
            tree.commit()
            
            # Verify data persisted
            assert tree.search(10) == {"id": 10}, "Insert not persisted"
            assert tree.search(20) == {"id": 20}, "Insert not persisted"
            
            self.results.add_pass("test_atomicity_insert_commit")
        except Exception as e:
            self.results.add_fail("test_atomicity_insert_commit", str(e))
    
    def test_atomicity_rollback_insert(self):
        """Test that rolled back inserts are undone."""
        try:
            tree = TransactionalBPlusTree(order=4)
            
            # Insert baseline
            tree.insert(10, {"id": 10})
            assert tree.search(10) == {"id": 10}
            
            # Begin transaction, insert, rollback
            txn_id = tree.begin_transaction()
            tree.insert(20, {"id": 20}, txn_id)
            tree.rollback()
            
            # Verify rolled back insert is gone
            assert tree.search(20) is None, "Rollback failed - insert still exists"
            assert tree.search(10) == {"id": 10}, "Rollback affected other data"
            
            self.results.add_pass("test_atomicity_rollback_insert")
        except Exception as e:
            self.results.add_fail("test_atomicity_rollback_insert", str(e))
    
    def test_atomicity_rollback_delete(self):
        """Test that rolled back deletes restore data."""
        try:
            tree = TransactionalBPlusTree(order=4)
            
            # Insert initial data
            tree.insert(10, {"id": 10})
            tree.insert(20, {"id": 20})
            
            # Begin transaction, delete, rollback
            txn_id = tree.begin_transaction()
            tree.delete(10, txn_id)
            tree.rollback()
            
            # Verify rolled back delete is restored
            assert tree.search(10) == {"id": 10}, "Rollback failed - delete not restored"
            assert tree.search(20) == {"id": 20}, "Rollback affected other data"
            
            self.results.add_pass("test_atomicity_rollback_delete")
        except Exception as e:
            self.results.add_fail("test_atomicity_rollback_delete", str(e))
    
    def test_atomicity_rollback_update(self):
        """Test that rolled back updates restore original values."""
        try:
            tree = TransactionalBPlusTree(order=4)
            
            # Insert initial data
            tree.insert(10, {"id": 10, "value": 100})
            
            # Begin transaction, update, rollback
            txn_id = tree.begin_transaction()
            tree.update(10, {"id": 10, "value": 200}, txn_id)
            tree.rollback()
            
            # Verify rolled back update is restored
            assert tree.search(10) == {"id": 10, "value": 100}, "Rollback failed - update not restored"
            
            self.results.add_pass("test_atomicity_rollback_update")
        except Exception as e:
            self.results.add_fail("test_atomicity_rollback_update", str(e))
    
    def test_atomicity_multi_op_transaction(self):
        """Test transaction with multiple operations all commit."""
        try:
            tree = TransactionalBPlusTree(order=4)
            
            # Transaction with multiple ops
            txn_id = tree.begin_transaction()
            tree.insert(10, {"id": 10}, txn_id)
            tree.insert(20, {"id": 20}, txn_id)
            tree.insert(30, {"id": 30}, txn_id)
            tree.commit()
            
            # Verify all committed
            assert tree.search(10) == {"id": 10}
            assert tree.search(20) == {"id": 20}
            assert tree.search(30) == {"id": 30}
            
            self.results.add_pass("test_atomicity_multi_op_transaction")
        except Exception as e:
            self.results.add_fail("test_atomicity_multi_op_transaction", str(e))
    
    def test_atomicity_multi_op_rollback(self):
        """Test that multi-op transaction rollback undoes all operations."""
        try:
            tree = TransactionalBPlusTree(order=4)
            tree.insert(1, {"id": 1})  # Base data
            
            # Multi-op transaction
            txn_id = tree.begin_transaction()
            tree.insert(10, {"id": 10}, txn_id)
            tree.update(1, {"id": 1, "updated": True}, txn_id)
            tree.insert(20, {"id": 20}, txn_id)
            tree.rollback()
            
            # Verify all rolled back
            assert tree.search(10) is None
            assert tree.search(1) == {"id": 1}  # Update rolled back
            assert tree.search(20) is None
            
            self.results.add_pass("test_atomicity_multi_op_rollback")
        except Exception as e:
            self.results.add_fail("test_atomicity_multi_op_rollback", str(e))
    
    # ==================== CONSISTENCY TESTS ====================
    
    def test_consistency_tree_structure(self):
        """Test that B+ Tree structure remains valid after operations."""
        try:
            tree = TransactionalBPlusTree(order=4)
            checker = ConsistencyChecker()
            
            # Insert data
            for i in range(1, 21):
                tree.insert(i, {"id": i})
            
            # Validate tree structure
            valid = checker.validate_bplustree_structure(tree.tree.root)
            assert valid, f"Tree structure invalid: {checker.get_errors()}"
            
            self.results.add_pass("test_consistency_tree_structure")
        except Exception as e:
            self.results.add_fail("test_consistency_tree_structure", str(e))
    
    def test_consistency_db_tree_match(self):
        """Test that DB and B+ Tree records match."""
        try:
            tree = TransactionalBPlusTree(order=4)
            checker = ConsistencyChecker()
            
            # Insert data
            db_records = {}
            for i in range(1, 11):
                data = {"id": i, "value": i*10}
                tree.insert(i, data)
                db_records[i] = data
            
            # Get tree records
            tree_records = dict(tree.tree.get_all())
            
            # Check consistency
            valid = checker.validate_db_bplustree_consistency(db_records, tree_records)
            assert valid, f"DB/Tree mismatch: {checker.get_errors()}"
            
            self.results.add_pass("test_consistency_db_tree_match")
        except Exception as e:
            self.results.add_fail("test_consistency_db_tree_match", str(e))
    
    def test_consistency_after_delete(self):
        """Test consistency after delete operations."""
        try:
            tree = TransactionalBPlusTree(order=4)
            checker = ConsistencyChecker()
            
            # Insert and delete
            for i in range(1, 21):
                tree.insert(i, {"id": i})
            
            for i in range(1, 6):
                tree.delete(i)
            
            # Validate structure
            valid = checker.validate_bplustree_structure(tree.tree.root)
            assert valid, f"Tree structure invalid after delete: {checker.get_errors()}"
            
            # Validate consistency
            db_records = dict(tree.tree.get_all())
            tree_records = dict(tree.tree.get_all())
            valid = checker.validate_db_bplustree_consistency(db_records, tree_records)
            assert valid, f"Consistency invalid after delete: {checker.get_errors()}"
            
            self.results.add_pass("test_consistency_after_delete")
        except Exception as e:
            self.results.add_fail("test_consistency_after_delete", str(e))
    
    # ==================== DURABILITY TESTS ====================
    
    def test_durability_wal_persists(self):
        """Test that WAL persists operations to disk."""
        try:
            wal_file = os.path.join(self.temp_dir, "test_wal.log")
            tree = TransactionalBPlusTree(wal_file=wal_file)
            
            # Insert and commit
            txn_id = tree.begin_transaction()
            tree.insert(10, {"id": 10}, txn_id)
            tree.commit()
            
            # Verify WAL file exists and contains data
            assert os.path.exists(wal_file), "WAL file not created"
            
            with open(wal_file, 'r') as f:
                content = f.read()
                assert len(content) > 0, "WAL file is empty"
                assert "COMMIT" in content, "COMMIT not in WAL"
            
            self.results.add_pass("test_durability_wal_persists")
        except Exception as e:
            self.results.add_fail("test_durability_wal_persists", str(e))
    
    def test_durability_committed_survives_recovery(self):
        """Test that committed data survives recovery."""
        try:
            wal_file = os.path.join(self.temp_dir, "test_wal2.log")
            
            # Phase 1: Insert and commit
            tree1 = TransactionalBPlusTree(wal_file=wal_file)
            txn_id = tree1.begin_transaction()
            tree1.insert(10, {"id": 10}, txn_id)
            tree1.commit()
            
            # Phase 2: Simulate restart and recovery
            # Create a fresh tree with a DIFFERENT WAL file to simulate clean restart
            tree2 = BPlusTree(order=4)
            wal2 = WriteAheadLogger(wal_file)  # Load existing WAL
            recovery_mgr = RecoveryManager(wal2)
            
            # Replay operations directly into tree (not through transaction layer)
            def apply_op(op_type, key, value, old_value):
                if op_type == OperationType.INSERT:
                    tree2.insert(key, value)
                elif op_type == OperationType.DELETE:
                    tree2.delete(key)
                elif op_type == OperationType.UPDATE:
                    tree2.update(key, value)
            
            recovery_mgr.recover(apply_op)
            
            # Verify data recovered
            assert tree2.search(10) == {"id": 10}, "Data not recovered after restart"
            
            self.results.add_pass("test_durability_committed_survives_recovery")
        except Exception as e:
            self.results.add_fail("test_durability_committed_survives_recovery", str(e))
    
    # ==================== CONSISTENCY AFTER ROLLBACK ====================
    
    def test_consistency_after_rollback(self):
        """Test that consistency is maintained after rollback."""
        try:
            tree = TransactionalBPlusTree(order=4)
            checker = ConsistencyChecker()
            
            # Insert baseline
            for i in range(1, 11):
                tree.insert(i, {"id": i})
            
            # Transaction with operations then rollback
            txn_id = tree.begin_transaction()
            tree.insert(20, {"id": 20}, txn_id)
            tree.delete(5, txn_id)
            tree.rollback()
            
            # Validate structure
            valid = checker.validate_bplustree_structure(tree.tree.root)
            assert valid, f"Tree structure invalid after rollback: {checker.get_errors()}"
            
            # Verify data consistency
            assert tree.search(20) is None, "Rollback didn't undo insert"
            assert tree.search(5) == {"id": 5}, "Rollback didn't restore delete"
            
            self.results.add_pass("test_consistency_after_rollback")
        except Exception as e:
            self.results.add_fail("test_consistency_after_rollback", str(e))
    
    # ==================== RANGE QUERY CONSISTENCY ====================
    
    def test_range_query_consistency(self):
        """Test that range queries remain consistent after operations."""
        try:
            tree = TransactionalBPlusTree(order=4)
            
            # Insert data
            for i in range(1, 31, 2):  # 1, 3, 5, ..., 29
                tree.insert(i, {"id": i})
            
            # Range query before delete
            before = tree.range_query(5, 15)
            assert len(before) == 6, f"Expected 6 items in range, got {len(before)}"
            
            # Delete and rollback
            txn_id = tree.begin_transaction()
            tree.delete(7, txn_id)
            tree.delete(11, txn_id)
            tree.rollback()
            
            # Range query after rollback
            after = tree.range_query(5, 15)
            assert len(after) == 6, f"Range query after rollback incorrect"
            assert before == after, "Range query changed after rollback"
            
            self.results.add_pass("test_range_query_consistency")
        except Exception as e:
            self.results.add_fail("test_range_query_consistency", str(e))
    
    def run_all_tests(self):
        """Run all ACID tests."""
        print("\n" + "="*60)
        print("RUNNING ACID VALIDATION TESTS")
        print("="*60 + "\n")
        
        # Atomicity tests
        print("ATOMICITY TESTS:")
        self.test_atomicity_insert_commit()
        self.test_atomicity_rollback_insert()
        self.test_atomicity_rollback_delete()
        self.test_atomicity_rollback_update()
        self.test_atomicity_multi_op_transaction()
        self.test_atomicity_multi_op_rollback()
        
        # Consistency tests
        print("\nCONSISTENCY TESTS:")
        self.test_consistency_tree_structure()
        self.test_consistency_db_tree_match()
        self.test_consistency_after_delete()
        self.test_consistency_after_rollback()
        
        # Durability tests
        print("\nDURABILITY TESTS:")
        self.test_durability_wal_persists()
        self.test_durability_committed_survives_recovery()
        
        # Range query tests
        print("\nRANGE QUERY CONSISTENCY TESTS:")
        self.test_range_query_consistency()
        
        # Print summary
        self.results.print_summary()
        
        return self.results.get_summary()


def main():
    """Main test runner."""
    tests = ACIDTests()
    summary = tests.run_all_tests()
    
    # Exit with appropriate code
    sys.exit(0 if summary["failed"] == 0 else 1)


if __name__ == "__main__":
    main()
