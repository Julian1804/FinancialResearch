第二轮补丁的简化补丁（round2.1）

目的：
1. 不再要求 .env 中配置模型名称；
2. 模型默认值放到 app/config/llm_profiles.json；
3. .env 只保留密钥、Base URL、默认 profile、数据路径/QNAP 配置。

覆盖文件：
- Research Assistant/app/config/settings.py
- Research Assistant/app/config/llm_profiles.json
- Research Assistant/.env.example

说明：
- 如果你当前 .env 里只有 ALIYUN/DEEPSEEK 的 API_KEY 与 BASE_URL，这个补丁更贴合你的实际使用方式；
- 后续切换模型时，优先改 llm_profiles.json 里的 model 字段；
- 如果未来某个提供商要求模型也从环境变量读取，仍可恢复 model_env 机制。
