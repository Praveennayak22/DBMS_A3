"""
Write-Ahead Logging (WAL) for transaction durability.

Ensures all operations are logged BEFORE they are applied,
allowing crash recovery and durability guarantees.
"""

import json
import os
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional


class OperationType(Enum):
    """Types of operations that can be logged."""
    INSERT = "INSERT"
    UPDATE = "UPDATE"
    DELETE = "DELETE"
    SPLIT_NODE = "SPLIT_NODE"
    MERGE_NODE = "MERGE_NODE"
    BEGIN = "BEGIN"
    COMMIT = "COMMIT"
    ABORT = "ABORT"


class LogEntry:
    """Represents a single log entry."""
    
    def __init__(self, 
                 txn_id: int,
                 op_type: OperationType,
                 timestamp: str,
                 key: Optional[Any] = None,
                 value: Optional[Any] = None,
                 old_value: Optional[Any] = None,
                 status: str = "PENDING"):
        self.txn_id = txn_id
        self.op_type = op_type
        self.timestamp = timestamp
        self.key = key
        self.value = value
        self.old_value = old_value
        self.status = status  # PENDING, COMMITTED, ABORTED
    
    def _serialize_value(self, val: Any) -> str:
        """Serialize a value to JSON string."""
        try:
            return json.dumps(val)
        except (TypeError, ValueError):
            # If not JSON serializable, convert to string
            return str(val)
    
    def _deserialize_value(self, val_str: str) -> Any:
        """Deserialize a value from JSON string."""
        if val_str is None:
            return None
        try:
            return json.loads(val_str)
        except (json.JSONDecodeError, ValueError):
            # If not valid JSON, return as string
            return val_str
    
    def to_dict(self) -> Dict:
        """Convert log entry to dictionary for serialization."""
        return {
            "txn_id": self.txn_id,
            "op_type": self.op_type.value,
            "timestamp": self.timestamp,
            "key": self._serialize_value(self.key) if self.key is not None else None,
            "value": self._serialize_value(self.value) if self.value is not None else None,
            "old_value": self._serialize_value(self.old_value) if self.old_value is not None else None,
            "status": self.status
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'LogEntry':
        """Create log entry from dictionary."""
        entry = cls.__new__(cls)
        entry.txn_id = data["txn_id"]
        entry.op_type = OperationType(data["op_type"])
        entry.timestamp = data["timestamp"]
        entry.status = data.get("status", "PENDING")
        
        # Deserialize values
        entry.key = entry._deserialize_value(data.get("key"))
        entry.value = entry._deserialize_value(data.get("value"))
        entry.old_value = entry._deserialize_value(data.get("old_value"))
        
        return entry
    
    def __repr__(self) -> str:
        return (f"LogEntry(txn_id={self.txn_id}, op={self.op_type.value}, "
                f"key={self.key}, status={self.status})")


class WriteAheadLogger:
    """Write-Ahead Logger for transaction logging and recovery."""
    
    def __init__(self, log_file: str = "module_a_wal.log"):
        self.log_file = Path(log_file)
        self.entries: List[LogEntry] = []
        self.in_memory_buffer: List[LogEntry] = []
        self._load_existing_log()
    
    def _load_existing_log(self):
        """Load existing log file on startup."""
        if self.log_file.exists():
            try:
                with open(self.log_file, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            data = json.loads(line)
                            entry = LogEntry.from_dict(data)
                            self.entries.append(entry)
            except Exception as e:
                print(f"Warning: Could not load existing WAL: {e}")
    
    def begin_transaction(self, txn_id: int):
        """Log the beginning of a transaction."""
        entry = LogEntry(
            txn_id=txn_id,
            op_type=OperationType.BEGIN,
            timestamp=datetime.utcnow().isoformat(),
            status="COMMITTED"
        )
        self.in_memory_buffer.append(entry)
    
    def log_operation(self, 
                     txn_id: int, 
                     op_type: OperationType,
                     key: Any,
                     value: Any = None,
                     old_value: Any = None):
        """Log a database operation."""
        entry = LogEntry(
            txn_id=txn_id,
            op_type=op_type,
            timestamp=datetime.utcnow().isoformat(),
            key=key,
            value=value,
            old_value=old_value,
            status="PENDING"
        )
        self.in_memory_buffer.append(entry)
    
    def commit(self, txn_id: int) -> bool:
        """Mark all operations of a transaction as committed."""
        try:
            # Mark all pending entries for this txn as committed
            for entry in self.in_memory_buffer:
                if entry.txn_id == txn_id and entry.status == "PENDING":
                    entry.status = "COMMITTED"
            
            # Log COMMIT entry
            commit_entry = LogEntry(
                txn_id=txn_id,
                op_type=OperationType.COMMIT,
                timestamp=datetime.utcnow().isoformat(),
                status="COMMITTED"
            )
            self.in_memory_buffer.append(commit_entry)
            
            # Persist all entries for this transaction
            self._flush_to_disk()
            return True
        except Exception as e:
            print(f"Error committing transaction {txn_id}: {e}")
            return False
    
    def abort(self, txn_id: int) -> bool:
        """Mark all operations of a transaction as aborted."""
        try:
            # Mark entries as aborted (don't write to disk, just track state)
            for entry in self.in_memory_buffer:
                if entry.txn_id == txn_id:
                    entry.status = "ABORTED"
            
            # Log ABORT entry
            abort_entry = LogEntry(
                txn_id=txn_id,
                op_type=OperationType.ABORT,
                timestamp=datetime.utcnow().isoformat(),
                status="COMMITTED"
            )
            self.in_memory_buffer.append(abort_entry)
            
            # Optionally persist abort (for logging purposes)
            self._flush_to_disk()
            return True
        except Exception as e:
            print(f"Error aborting transaction {txn_id}: {e}")
            return False
    
    def _flush_to_disk(self):
        """Flush in-memory buffer to disk."""
        try:
            with open(self.log_file, 'a', encoding='utf-8') as f:
                for entry in self.in_memory_buffer:
                    json_line = json.dumps(entry.to_dict())
                    f.write(json_line + "\n")
                    self.entries.append(entry)
            self.in_memory_buffer.clear()
        except Exception as e:
            print(f"Error flushing to disk: {e}")
    
    def get_committed_transactions(self) -> Dict[int, List[LogEntry]]:
        """Get all entries grouped by committed transaction."""
        txn_entries = {}
        
        for entry in self.entries:
            if entry.txn_id not in txn_entries:
                txn_entries[entry.txn_id] = []
            txn_entries[entry.txn_id].append(entry)
        
        # Filter to only committed transactions
        committed = {}
        for txn_id, entries in txn_entries.items():
            # Check if transaction has COMMIT entry
            has_commit = any(e.op_type == OperationType.COMMIT for e in entries)
            if has_commit:
                committed[txn_id] = entries
        
        return committed
    
    def get_transaction_entries(self, txn_id: int) -> List[LogEntry]:
        """Get all entries for a specific transaction."""
        return [e for e in self.entries if e.txn_id == txn_id]
    
    def clear_log(self):
        """Clear the log (for testing purposes)."""
        self.entries.clear()
        self.in_memory_buffer.clear()
        if self.log_file.exists():
            os.remove(self.log_file)
    
    def get_log_statistics(self) -> Dict:
        """Get statistics about the log."""
        committed = 0
        aborted = 0
        pending = 0
        
        for entry in self.entries:
            if entry.status == "COMMITTED":
                committed += 1
            elif entry.status == "ABORTED":
                aborted += 1
            else:
                pending += 1
        
        return {
            "total_entries": len(self.entries),
            "committed": committed,
            "aborted": aborted,
            "pending": pending,
            "buffer_size": len(self.in_memory_buffer),
            "log_file": str(self.log_file)
        }
    
    def __repr__(self) -> str:
        stats = self.get_log_statistics()
        return (f"WriteAheadLogger(entries={stats['total_entries']}, "
                f"committed={stats['committed']}, pending={stats['pending']})")
