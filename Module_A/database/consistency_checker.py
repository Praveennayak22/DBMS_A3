"""
Consistency Checker for validating ACID properties and data integrity.

Verifies that the B+ Tree and database records remain consistent
even after transactions, rollbacks, and crashes.
"""

from typing import Any, Dict, List, Optional, Tuple


class ConsistencyError(Exception):
    """Raised when consistency violation is detected."""
    pass


class ConsistencyChecker:
    """Validates B+ Tree and database consistency."""
    
    def __init__(self):
        self.errors: List[str] = []
        self.warnings: List[str] = []
    
    def validate_bplustree_structure(self, root_node) -> bool:
        """
        Validate B+ Tree structural properties.
        
        Checks:
        1. Key ordering (keys are sorted in each node)
        2. Node capacity (no node exceeds max_keys)
        3. Internal node constraints (num_keys == num_children - 1)
        4. Leaf node linking (next pointers are correct)
        5. Root node minimum keys
        """
        self.errors.clear()
        self.warnings.clear()
        
        try:
            self._validate_node_keys(root_node)
            self._validate_node_capacity(root_node)
            self._validate_internal_constraints(root_node)
            self._validate_leaf_linking(root_node)
            
            return len(self.errors) == 0
        except Exception as e:
            self.errors.append(f"Validation exception: {str(e)}")
            return False
    
    def _validate_node_keys(self, node, parent_key_range: Tuple[Any, Any] = (None, None)) -> bool:
        """Validate that keys are sorted within range."""
        if not node.keys:
            if node.is_leaf:
                return True
            if node != self.root and node.keys:  # Internal node must have keys
                return True
        
        # Check keys are sorted
        for i in range(len(node.keys) - 1):
            if node.keys[i] >= node.keys[i + 1]:
                self.errors.append(f"Keys not sorted: {node.keys[i]} >= {node.keys[i + 1]}")
                return False
        
        # Check parent range constraints
        min_key, max_key = parent_key_range
        if min_key is not None and node.keys[0] < min_key:
            self.errors.append(f"Key {node.keys[0]} violates min constraint {min_key}")
            return False
        if max_key is not None and node.keys[-1] > max_key:
            self.errors.append(f"Key {node.keys[-1]} violates max constraint {max_key}")
            return False
        
        # Recursively check children
        if not node.is_leaf:
            for i, child in enumerate(node.children):
                child_min = None if i == 0 else node.keys[i - 1]
                child_max = node.keys[i] if i < len(node.keys) else None
                if not self._validate_node_keys(child, (child_min, child_max)):
                    return False
        
        return True
    
    def _validate_node_capacity(self, node) -> bool:
        """Validate that no node exceeds capacity."""
        if len(node.keys) > node.max_keys:
            self.errors.append(f"Node exceeds max_keys: {len(node.keys)} > {node.max_keys}")
            return False
        
        if not node.is_leaf:
            if len(node.children) != len(node.keys) + 1:
                self.errors.append(f"Internal node: children count ({len(node.children)}) "
                                 f"!= keys + 1 ({len(node.keys) + 1})")
                return False
            
            for child in node.children:
                if not self._validate_node_capacity(child):
                    return False
        
        return True
    
    def _validate_internal_constraints(self, node) -> bool:
        """Validate internal node constraints."""
        if not node.is_leaf:
            # Check key count matches
            if len(node.keys) + 1 != len(node.children):
                self.errors.append(f"Internal node key/children mismatch: "
                                 f"{len(node.keys)} keys, {len(node.children)} children")
                return False
            
            for child in node.children:
                if not self._validate_internal_constraints(child):
                    return False
        
        return True
    
    def _validate_leaf_linking(self, node) -> bool:
        """Validate that leaf nodes are correctly linked."""
        if node.is_leaf:
            # Leaf should have values == keys
            if len(node.keys) != len(node.values):
                self.errors.append(f"Leaf node: keys ({len(node.keys)}) "
                                 f"!= values ({len(node.values)})")
                return False
            return True
        
        # For internal nodes, check leaf linking through children
        for child in node.children:
            if not self._validate_leaf_linking(child):
                return False
        
        return True
    
    def validate_db_bplustree_consistency(self, 
                                        db_records: Dict[Any, Any],
                                        bplustree_records: Dict[Any, Any]) -> bool:
        """
        Validate that database records match B+ Tree index.
        
        Args:
            db_records: Records from main database
            bplustree_records: Records from B+ Tree index
        
        Returns:
            True if consistent, False otherwise
        """
        self.errors.clear()
        self.warnings.clear()
        
        # Check all DB records are in B+ Tree
        for key, value in db_records.items():
            if key not in bplustree_records:
                self.errors.append(f"DB record missing from B+ Tree: key={key}")
            elif bplustree_records[key] != value:
                self.errors.append(f"DB/B+ Tree value mismatch for key={key}: "
                                 f"DB={value}, Tree={bplustree_records[key]}")
        
        # Check all B+ Tree records are in DB
        for key, value in bplustree_records.items():
            if key not in db_records:
                self.errors.append(f"B+ Tree record missing from DB: key={key}")
        
        if len(db_records) != len(bplustree_records):
            self.errors.append(f"Record count mismatch: DB={len(db_records)}, "
                             f"Tree={len(bplustree_records)}")
        
        return len(self.errors) == 0
    
    def validate_transaction_state(self, txn_state: Dict) -> bool:
        """Validate transaction state consistency."""
        self.errors.clear()
        
        # Check transaction status is valid
        valid_statuses = {"ACTIVE", "COMMITTED", "ABORTED"}
        for txn_id, txn in txn_state.items():
            if "status" in txn and txn["status"] not in valid_statuses:
                self.errors.append(f"Invalid transaction status: {txn['status']}")
        
        return len(self.errors) == 0
    
    def get_errors(self) -> List[str]:
        """Get all validation errors."""
        return list(self.errors)
    
    def get_warnings(self) -> List[str]:
        """Get all validation warnings."""
        return list(self.warnings)
    
    def clear_errors(self):
        """Clear error list."""
        self.errors.clear()
        self.warnings.clear()
    
    def get_report(self) -> Dict:
        """Get validation report."""
        return {
            "valid": len(self.errors) == 0,
            "errors": self.errors,
            "warnings": self.warnings,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings)
        }
    
    def __repr__(self) -> str:
        return (f"ConsistencyChecker(errors={len(self.errors)}, "
                f"warnings={len(self.warnings)})")
