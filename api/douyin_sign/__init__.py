"""抖音 Web 端请求签名(纯 Python 移植)。

`abogus.py` / `sm3.py` / `websign.py` 移植自
Evil0ctal/Douyin_TikTok_Download_API(v5,Apache License 2.0)的
``src/dtk/signing/native/``,保留原作者版权声明;仅将 ``dtk`` 包内导入
改为相对导入,算法逐字节一致(已验证可产出平台接受的 a_bogus 与
x-secsdk-web-signature)。

签名对象 = (uifid, timestamp, SALT, query)。uifid 必须来自真实浏览器
会话(由页面 secsdk 生成,服务端校验),因此本包配合 `api.douyin_mint`
铸造的访客身份使用:Chrome 访问一次抖音页面拿 UIFID_TEMP / s_v_web_id /
ttwid 等 Cookie,随后所有请求在本进程内纯 Python 出签,无需再开浏览器。
"""

from .abogus import ABogus
from .sm3 import sm3_to_array
from .websign import (
    SALT,
    VERIFY_FP_PARAMS,
    encode_pairs,
    pick_uifid,
)
from .websign import (
    sign as websign_sign,
)

__all__ = [
    "SALT",
    "VERIFY_FP_PARAMS",
    "ABogus",
    "encode_pairs",
    "pick_uifid",
    "sm3_to_array",
    "websign_sign",
]
