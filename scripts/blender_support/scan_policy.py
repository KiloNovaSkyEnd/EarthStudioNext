"""Creative exports never select a known missing satellite texture."""

def safe_scan_index(nodes,nominal,previous=None):
    if not 0<=nominal<len(nodes):raise ValueError('计划扫描超出素材范围；停止导出')
    if not nodes[nominal]['missing']:return nominal
    if previous is not None:
        actual=previous[nominal]
    else:
        actual=nominal-1
        while actual>=0 and nodes[actual]['missing']:actual-=1
    if actual is None or actual<0:
        raise ValueError('该镜头起始时段缺少卫星观测，且没有此前有效观测可保持；停止导出，避免空地球')
    if nodes[actual]['missing']:raise ValueError('没有可用的有效观测；停止导出')
    return actual
