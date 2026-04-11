本轮补丁说明
1. 主页面新增“正式版工作台”入口，测试版仍保留独立页面。
2. 新增 LLM Profile + Failover 网关：
   - 优先走阿里云免费模型池
   - 单个模型 404 / quota / rate limit 时自动切到下一个
   - 阿里云文本池失败后再回退到 DeepSeek
3. Parse 复杂页接入阿里视觉模型（qwen-vl-ocr-latest 等）并保留失败回退。
4. 新增行业化指标 profile：
   - CRO/CDMO、半导体、矿业、医疗器械、消费
   - Metrics 会显示当前识别到的 profile 及推荐指标
5. actuals 严格过滤：
   - 只有主时序正式财报才能进入 actual_metrics_registry
   - 辅助材料只保留为信号，不进入 actuals
