"""
Transactional B+ Tree with ACID support.

Extends the base B+ Tree with transaction management,
write-ahead logging, and rollback capabilities.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, List, Optional, Tuple, Dict
from bplustree import BPlusTree, BPlusTreeNode
from write_ahead_logger import WriteAheadLogger, OperationType
from transaction_manager import TransactionManager


class TransactionalBPlusTree:
    """
    B+ Tree with transaction support.
    
    All operations are logged before execution (WAL) and can be rolled back.
    """
    
    def __init__(self, order: int = 4, 
                 wal_file: str = "module_a_wal.log"):
        self.tree = BPlusTree(order=order)
        self.txn_manager = TransactionManager()
        self.wal = WriteAheadLogger(wal_file)
        self.current_txn_id: Optional[int] = None
    
    def begin_transaction(self) -> int:
        """Begin a new transaction."""
        if self.current_txn_id is not None:
            raise RuntimeError("Transaction already active")
        
        txn_id = self.txn_manager.begin_transaction()
        self.wal.begin_transaction(txn_id)
        self.current_txn_id = txn_id
        
        return txn_id
    
    def insert(self, key: Any, value: Any, txn_id: Optional[int] = None) -> bool:
        """
        Insert with transaction support.
        
        If no txn_id provided, creates an auto-commit transaction.
        """
        if txn_id is None:
            if self.current_txn_id is not None:
                txn_id = self.current_txn_id
            else:
                # Auto-commit transaction
                txn_id = self.begin_transaction()
                auto_commit = True
        else:
            auto_commit = False
        
        try:
            # Check if key exists (for update case)
            old_value = self.tree.search(key)
            
            # Log operation
            self.wal.log_operation(txn_id, OperationType.INSERT, key, value, old_value)
            self.txn_manager.add_operation(txn_id, "INSERT", key, value, old_value)
            
            # Perform operation
            self.tree.insert(key, value)
            
            if auto_commit:
                self.commit()
            
            return True
        except Exception as e:
            if auto_commit and txn_id in self.txn_manager.transactions:
                self.rollback()
            print(f"Error in insert: {e}")
            return False
    
    def delete(self, key: Any, txn_id: Optional[int] = None) -> bool:
        """
        Delete with transaction support.
        """
        if txn_id is None:
            if self.current_txn_id is not None:
                txn_id = self.current_txn_id
            else:
                # Auto-commit transaction
                txn_id = self.begin_transaction()
                auto_commit = True
        else:
            auto_commit = False
        
        try:
            # Get old value
            old_value = self.tree.search(key)
            
            # Log operation
            self.wal.log_operation(txn_id, OperationType.DELETE, key, None, old_value)
            self.txn_manager.add_operation(txn_id, "DELETE", key, None, old_value)
            
            # Perform operation
            success = self.tree.delete(key)
            
            if not success and auto_commit:
                self.rollback()
                return False
            
            if auto_commit:
                self.commit()
            
            return success
        except Exception as e:
            if auto_commit and txn_id in self.txn_manager.transactions:
                self.rollback()
            print(f"Error in delete: {e}")
            return False
    
    def search(self, key: Any) -> Any:
        """Search without transaction (read-only, no logging needed)."""
        return self.tree.search(key)
    
    def update(self, key: Any, new_value: Any, txn_id: Optional[int] = None) -> bool:
        """
        Update with transaction support.
        """
        if txn_id is None:
            if self.current_txn_id is not None:
                txn_id = self.current_txn_id
            else:
                # Auto-commit transaction
                txn_id = self.begin_transaction()
                auto_commit = True
        else:
            auto_commit = False
        
        try:
            # Get old value
            old_value = self.tree.search(key)
            
            if old_value is None:
                raise ValueError(f"Key {key} not found")
            
            # Log operation
            self.wal.log_operation(txn_id, OperationType.UPDATE, key, new_value, old_value)
            self.txn_manager.add_operation(txn_id, "UPDATE", key, new_value, old_value)
            
            # Perform operation
            success = self.tree.update(key, new_value)
            
            if not success and auto_commit:
                self.rollback()
                return False
            
            if auto_commit:
                self.commit()
            
            return success
        except Exception as e:
            if auto_commit and txn_id in self.txn_manager.transactions:
                self.rollback()
            print(f"Error in update: {e}")
            return False
    
    def range_query(self, start_key: Any, end_key: Any) -> List:
        """Range query without transaction."""
        return self.tree.range_query(start_key, end_key)
    
    def commit(self) -> bool:
        """Commit current transaction."""
        if self.current_txn_id is None:
            raise RuntimeError("No active transaction")
        
        txn_id = self.current_txn_id
        
        try:
            # Mark all operations as committed
            self.txn_manager.commit(txn_id)
            self.wal.commit(txn_id)
            self.current_txn_id = None
            return True
        except Exception as e:
            print(f"Error in commit: {e}")
            return False
    
    def rollback(self) -> bool:
        """Rollback current transaction."""
        if self.current_txn_id is None:
            raise RuntimeError("No active transaction")
        
        txn_id = self.current_txn_id
        txn = self.txn_manager.get_transaction(txn_id)
        
        try:
            # Undo operations in reverse order
            for undo_op in txn.get_undo_operations():
                if undo_op["type"] == "INSERT":
                    # Undo insert by deleting
                    self.tree.delete(undo_op["key"])
                elif undo_op["type"] == "DELETE":
                    # Undo delete by reinserting
                    self.tree.insert(undo_op["key"], undo_op["old_value"])
                elif undo_op["type"] == "UPDATE":
                    # Undo update by restoring old value
                    self.tree.update(undo_op["key"], undo_op["old_value"])
            
            # Mark as aborted
            self.txn_manager.abort(txn_id)
            self.wal.abort(txn_id)
            self.current_txn_id = None
            return True
        except Exception as e:
            print(f"Error in rollback: {e}")
            return False
    
    def get_all(self) -> List:
        """Get all records from tree."""
        return self.tree.get_all()
    
    def get_transaction_stats(self) -> Dict:
        """Get transaction statistics."""
        return self.txn_manager.get_statistics()
    
    def get_wal_stats(self) -> Dict:
        """Get WAL statistics."""
        return self.wal.get_log_statistics()
    
    def __repr__(self) -> str:
        return (f"TransactionalBPlusTree(txn={self.current_txn_id}, "
                f"tree_order={self.tree.order})")
