"""Interactive local-only entry point. Run via configure_eumetsat.bat."""
import getpass
import sys
import warnings

from ges.eumetsat_auth import authenticated_token, save_credentials


def main():
    if hasattr(sys.stdout,'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        print('请双击 configure_eumetsat.bat，在本地交互终端配置。')
        return 1
    print('从 https://api.eumetsat.int/api-key 获取 Consumer Key 和 Consumer Secret。')
    print('这不是登录密码。输入内容隐藏；不会打印密钥或访问令牌。')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error',getpass.GetPassWarning)
            key=getpass.getpass('Consumer Key: ').strip()
            secret=getpass.getpass('Consumer Secret: ').strip()
        if not key or not secret:
            print('输入为空，未保存。')
            return 1
        print('正在向 EUMETSAT 官方服务验证……')
        authenticated_token((key,secret))
        save_credentials(key,secret)
    except KeyboardInterrupt:
        print('\n已取消，未保存新凭据。')
        return 1
    except Exception:
        # SDK/server errors can include sensitive request details; do not echo.
        print('验证或加密保存未成功，未输出任何密钥或令牌。请检查官方 API 密钥与网络后重试。')
        return 1
    print('认证成功，凭据已用 Windows 当前用户 DPAPI 加密保存。')
    print('未下载卫星文件；具体数据许可和下载接口仍需实际验证。')
    return 0


if __name__=='__main__':
    raise SystemExit(main())
