"""
Transaction Manager for managing transaction lifecycle and ACID properties.

Handles transaction begin, commit, rollback, and maintains transaction state.
"""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


class TransactionStatus(Enum):
    """Status of a transaction."""
    ACTIVE = "ACTIVE"
    COMMITTED = "COMMITTED"
    ABORTED = "ABORTED"


class Transaction:
    """Represents a single database transaction."""
    
    def __init__(self, txn_id: int):
        self.txn_id = txn_id
        self.status = TransactionStatus.ACTIVE
        self.start_time = datetime.utcnow()
        self.end_time: Optional[datetime] = None
        self.operations: List[Dict] = []  # Track operations for rollback
    
    def add_operation(self, op_type: str, key: Any, value: Any = None, old_value: Any = None):
        """Add an operation to this transaction."""
        self.operations.append({
            "type": op_type,
            "key": key,
            "value": value,
            "old_value": old_value,
            "timestamp": datetime.utcnow().isoformat()
        })
    
    def commit(self):
        """Mark transaction as committed."""
        self.status = TransactionStatus.COMMITTED
        self.end_time = datetime.utcnow()
    
    def abort(self):
        """Mark transaction as aborted."""
        self.status = TransactionStatus.ABORTED
        self.end_time = datetime.utcnow()
    
    def get_undo_operations(self) -> List[Dict]:
        """Get operations in reverse order for rollback (LIFO)."""
        return list(reversed(self.operations))
    
    def duration_ms(self) -> float:
        """Get transaction duration in milliseconds."""
        if self.end_time is None:
            duration = datetime.utcnow() - self.start_time
        else:
            duration = self.end_time - self.start_time
        return duration.total_seconds() * 1000
    
    def __repr__(self) -> str:
        return (f"Transaction(id={self.txn_id}, status={self.status.value}, "
                f"ops={len(self.operations)}, duration={self.duration_ms():.2f}ms)")


class TransactionManager:
    """Manages transaction lifecycle, commit, and rollback."""
    
    def __init__(self):
        self.transactions: Dict[int, Transaction] = {}
        self.next_txn_id = 1
        self.active_transactions: set = set()
        self.committed_transactions: Dict[int, Transaction] = {}
        self.aborted_transactions: Dict[int, Transaction] = {}
    
    def begin_transaction(self) -> int:
        """Begin a new transaction and return its ID."""
        txn_id = self.next_txn_id
        self.next_txn_id += 1
        
        txn = Transaction(txn_id)
        self.transactions[txn_id] = txn
        self.active_transactions.add(txn_id)
        
        return txn_id
    
    def get_transaction(self, txn_id: int) -> Optional[Transaction]:
        """Get transaction by ID."""
        return self.transactions.get(txn_id)
    
    def is_active(self, txn_id: int) -> bool:
        """Check if transaction is active."""
        return txn_id in self.active_transactions
    
    def add_operation(self, txn_id: int, op_type: str, key: Any, 
                      value: Any = None, old_value: Any = None):
        """Add an operation to a transaction."""
        if txn_id not in self.transactions:
            raise ValueError(f"Transaction {txn_id} not found")
        
        txn = self.transactions[txn_id]
        if txn.status != TransactionStatus.ACTIVE:
            raise ValueError(f"Transaction {txn_id} is not active (status={txn.status.value})")
        
        txn.add_operation(op_type, key, value, old_value)
    
    def commit(self, txn_id: int) -> bool:
        """Commit a transaction."""
        if txn_id not in self.transactions:
            raise ValueError(f"Transaction {txn_id} not found")
        
        txn = self.transactions[txn_id]
        if txn.status != TransactionStatus.ACTIVE:
            raise ValueError(f"Cannot commit non-active transaction {txn_id}")
        
        txn.commit()
        self.active_transactions.discard(txn_id)
        self.committed_transactions[txn_id] = txn
        
        return True
    
    def abort(self, txn_id: int) -> bool:
        """Abort a transaction."""
        if txn_id not in self.transactions:
            raise ValueError(f"Transaction {txn_id} not found")
        
        txn = self.transactions[txn_id]
        if txn.status != TransactionStatus.ACTIVE:
            raise ValueError(f"Cannot abort non-active transaction {txn_id}")
        
        txn.abort()
        self.active_transactions.discard(txn_id)
        self.aborted_transactions[txn_id] = txn
        
        return True
    
    def get_committed_transactions(self) -> Dict[int, Transaction]:
        """Get all committed transactions."""
        return dict(self.committed_transactions)
    
    def get_active_transactions(self) -> Dict[int, Transaction]:
        """Get all active transactions."""
        active = {}
        for txn_id in self.active_transactions:
            if txn_id in self.transactions:
                active[txn_id] = self.transactions[txn_id]
        return active
    
    def get_statistics(self) -> Dict:
        """Get transaction manager statistics."""
        return {
            "active": len(self.active_transactions),
            "committed": len(self.committed_transactions),
            "aborted": len(self.aborted_transactions),
            "total": len(self.transactions),
            "next_txn_id": self.next_txn_id
        }
    
    def clear(self):
        """Clear all transactions (for testing)."""
        self.transactions.clear()
        self.active_transactions.clear()
        self.committed_transactions.clear()
        self.aborted_transactions.clear()
        self.next_txn_id = 1
    
    def __repr__(self) -> str:
        stats = self.get_statistics()
        return (f"TransactionManager(active={stats['active']}, "
                f"committed={stats['committed']}, aborted={stats['aborted']})")
