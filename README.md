# 清远港华燃气Home Assistant集成
通过Home Assistant获取港华燃气余额数据

# 安装
1. 通过HACS添加自定义仓库
2. 搜索"Towngas" 
3. 点击安装
   
# 使用
输入subsCode（用户号）、orgCode（区域码）、updatetime（更新间隔默认10分钟)

# 获取用户号、区域码
打开清远港华燃气网址：https://qingyuan.towngasvcc.com/home
登录自己的燃气账号，打开业务办理>账单缴费，网址加载完后为：https://qingyuan.towngasvcc.com/business/pay/owe/QYXXX/16XXXXX?single=1
QYXXX为区域码，16XXXXX为用户号

# 非清远地区可尝试修改api地址
因为没账号测试，非清远地区可尝试修改sensor.py文件里面的api地址，把“https://qingyuan.towngasvcc.com/openapi/uv1/biz/checkRouters”修改成对应地区的api地址
