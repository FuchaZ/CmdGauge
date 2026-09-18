import os
import sys

# 让 pytest 能从 tests/ 目录导入仓库根下的 app 包
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
