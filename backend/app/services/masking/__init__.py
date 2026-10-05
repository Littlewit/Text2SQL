"""脱敏服务包：服务端结果集出口统一脱敏（FR-SEC-20~23）。"""

from app.services.masking.engine import ColumnMaskInfo, detect_mask_type, mask_rows

__all__ = ["ColumnMaskInfo", "mask_rows", "detect_mask_type"]
