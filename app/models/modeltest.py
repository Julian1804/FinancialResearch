import os
import sys
from openai import OpenAI

# ==================== 配置区域 ====================
API_KEY = "sk-5de6f3b26282406c983d4231fa07f3d1"  # 替换成你的真实 API Key
MODEL = "qwen-plus"            # 可选: qwen-turbo, qwen-plus, qwen-max
# =================================================

def test_qwen():
    """最小化测试：验证千问API是否调用成功"""
    
    client = OpenAI(
        api_key=API_KEY,
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    )
    
    try:
        print("正在调用千问 API...", end=" ", flush=True)
        
        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "user", "content": "请用一句话介绍你自己"}
            ],
            max_tokens=50,  # 最小消耗，省点钱
            temperature=0.7,
        )
        
        print("✓ 调用成功！")
        print("-" * 50)
        print(f"模型: {response.model}")
        print(f"回复: {response.choices[0].message.content}")
        print(f"消耗 Token: {response.usage.total_tokens}")
        print("-" * 50)
        
        return True
        
    except Exception as e:
        print(f"✗ 调用失败")
        print(f"错误信息: {str(e)}")
        return False

if __name__ == "__main__":
    print("=" * 50)
    print("阿里千问 DashScope API 连接测试")
    print("=" * 50)
    
    if API_KEY == "your-api-key-here":
        print("⚠️ 请先在脚本中设置你的真实 API Key")
        sys.exit(1)
    
    success = test_qwen()
    sys.exit(0 if success else 1)