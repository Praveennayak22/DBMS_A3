# Module A - Lightweight DBMS with B+ Tree Index

## What is included
- `database/bplustree.py`: Full B+ Tree implementation with insert, delete, search, update, range query, aggregation, and Graphviz visualisation.
- `database/bruteforce.py`: Linear baseline store for comparison.
- `database/table.py`: Table abstraction that stores records by key.
- `database/db_manager.py`: Multi-table manager.
- `benchmark.py`: Automated benchmark runner with Matplotlib plots and memory usage comparison.
- `report.ipynb`: Assignment report notebook scaffold with runnable cells.

## Quick run
```bash
pip install -r requirements.txt
python benchmark.py
```

## Graphviz notes
Install Graphviz system binaries to render PNG output from DOT:
- Windows: install from graphviz.org and ensure `dot` is in PATH.
