# 主工作区清洁启动包

用户在E:/beside仍不能直接双击启动。旧入口依赖系统Python与进程继承的环境变量；依赖不全和已保存但未继承的Profile分别会失败，后者原来还被统一提示成Python缺失。

启动层窄修：START-GUI优先包内_runtime/python.exe；运行阶段错误不再冒称依赖失败。gui_delivery在进程没有启动Profile设置时读取Windows当前用户已保存的同名启动设置，显式参数优先；不读取或复制密钥，不改变业务owner/权限/确认。

tools/build_clean_gui.py按白名单重建，输出目录必须不存在，不递归清理旧文件。只含当前app/gui入口、官方虚构样例、独立Python3.12与现有requirements依赖、公开Profile身份及说明。包内默认配置明确，无需依赖系统py、venv或进程Profile变量。现有Windows用户凭据仍由Vault读取；不能把其他机器缺凭据伪装成开箱已认证。

不复制历史账簿、会话、Trace、批准、local配置、密钥、开发产物或虚拟环境。使用说明明确当前业务限制；启动通过不冒充业务链通过。检查将在独立解压目录、带空格路径及无启动环境变量的新进程中完成，零模型请求；记录在artifacts/clean-package-20261122。

## 实际完成

最终包源SHA cb36efa，使用官方CPython Windows x64 embed 3.12.10（python.org下载，固定SHA256在构建器）。独立解压、路径含空格、PATH无Python、无Profile/密钥环境变量、错误Python覆盖路径的新进程，无参数启动包内cmd成功，HTTP根页面及snapshot均200。实际清洁包manifest核对2623个文件，交付目录无运行数据；ZIP 20,615,531字节。

首次构建因开发运行时专属证书被拦截，改为官方运行时；实际解压又发现遗漏固定sqlglot wheel，补入原wheel与来源说明后通过。失败产物移至artifacts归档，不递归删除用户文件。最终清洁目录仅保留cb36efa目录、ZIP与说明。测试数据只在artifacts的独立解压目录，模型调用0，真人GUI未验，业务首分及缺口不变。验证服务已停止，端口释放。包及各文件哈希见artifacts/clean-package-20261122/FINAL.public.json。
