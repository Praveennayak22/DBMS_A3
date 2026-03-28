"""
Recovery Manager for crash recovery and WAL replay.

Enables recovery from crashes by replaying committed transactions from the log.
"""

from typing import Any, Callable, Dict, List, Optional, Tuple
from write_ahead_logger import WriteAheadLogger, OperationType, LogEntry


class RecoveryManager:
    """Handles crash recovery using WAL."""
    
    def __init__(self, wal: WriteAheadLogger):
        self.wal = wal
        self.recovered = False
        self.recovered_state: Dict[int, Tuple[Any, Any]] = {}  # key -> (old_value, new_value)
    
    def recover(self, apply_operation: Callable) -> Dict:
        """
        Replay committed transactions from the log.
        
        Args:
            apply_operation: Callback function to apply operations: 
                           apply_operation(op_type, key, value, old_value)
        
        Returns:
            Recovery statistics
        """
        stats = {
            "total_entries": 0,
            "replayed_operations": 0,
            "skipped_operations": 0,
            "recovery_errors": 0
        }
        
        committed_txns = self.wal.get_committed_transactions()
        
        for txn_id, entries in committed_txns.items():
            for entry in entries:
                stats["total_entries"] += 1
                
                # Skip transaction control entries
                if entry.op_type in [OperationType.BEGIN, OperationType.COMMIT, OperationType.ABORT]:
                    stats["skipped_operations"] += 1
                    continue
                
                # Skip aborted operations
                if entry.status == "ABORTED":
                    stats["skipped_operations"] += 1
                    continue
                
                try:
                    # Replay the operation
                    apply_operation(
                        entry.op_type,
                        entry.key,
                        entry.value,
                        entry.old_value
                    )
                    self.recovered_state[entry.key] = (entry.old_value, entry.value)
                    stats["replayed_operations"] += 1
                except Exception as e:
                    stats["recovery_errors"] += 1
                    print(f"Error replaying operation {entry}: {e}")
        
        self.recovered = True
        return stats
    
    def get_recovered_state(self) -> Dict[Any, Tuple[Any, Any]]:
        """Get the recovered state (key -> (old_value, new_value))."""
        return dict(self.recovered_state)
    
    def __repr__(self) -> str:
        return (f"RecoveryManager(recovered={self.recovered}, "
                f"state_entries={len(self.recovered_state)})")


class CheckpointManager:
    """Manages checkpoints for faster recovery."""
    
    def __init__(self, checkpoint_file: str = "module_a_checkpoint.json"):
        self.checkpoint_file = checkpoint_file
        self.last_checkpoint: Optional[Dict] = None
    
    def create_checkpoint(self, tree_state: Dict, txn_state: Dict) -> bool:
        """Create a checkpoint of current database state."""
        try:
            import json
            from pathlib import Path
            
            checkpoint_data = {
                "timestamp": __import__('datetime').datetime.utcnow().isoformat(),
                "tree_state": tree_state,
                "txn_state": txn_state
            }
            
            with open(self.checkpoint_file, 'w', encoding='utf-8') as f:
                json.dump(checkpoint_data, f, indent=2)
            
            self.last_checkpoint = checkpoint_data
            return True
        except Exception as e:
            print(f"Error creating checkpoint: {e}")
            return False
    
    def load_checkpoint(self) -> Optional[Dict]:
        """Load the last checkpoint."""
        try:
            import json
            from pathlib import Path
            
            if Path(self.checkpoint_file).exists():
                with open(self.checkpoint_file, 'r', encoding='utf-8') as f:
                    self.last_checkpoint = json.load(f)
                    return self.last_checkpoint
        except Exception as e:
            print(f"Error loading checkpoint: {e}")
        
        return None
    
    def clear_checkpoint(self):
        """Clear the checkpoint file."""
        try:
            from pathlib import Path
            if Path(self.checkpoint_file).exists():
                Path(self.checkpoint_file).unlink()
            self.last_checkpoint = None
        except Exception as e:
            print(f"Error clearing checkpoint: {e}")
    
    def __repr__(self) -> str:
        has_checkpoint = self.last_checkpoint is not None
        return f"CheckpointManager(checkpoint_exists={has_checkpoint})"
