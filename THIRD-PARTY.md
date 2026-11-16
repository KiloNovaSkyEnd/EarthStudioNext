# 第三方组件与数据来源

- Blender 5.2.1 LTS 由 Blender Foundation 分发。附加包保留原发行版的版权及许可文件。[官方二进制、校验文件与对应源码](https://download.blender.org/release/Blender5.2/)。
- .NET、Windows App SDK 和 Cesium 使用各自随包提供的第三方声明。Cesium 版权与许可位于 `native/EarthStudio.App/Cesium/vendor`。
- 科学 Python 和 AI-VIS Python 使用 CPython Windows embeddable distribution。运行时保留 CPython 许可和依赖的 `.dist-info` 许可元数据。[CPython Windows 发行文件](https://www.python.org/downloads/release/python-31210/)。
- AI-VIS 1.0 由 Dapiya 发布，权重许可为 Apache-2.0。[推理源码](https://github.com/Dapiya/AI-VIS) · [权重](https://huggingface.co/Dapiya/aivis-1.0)。AI 运行时同时保留 PyTorch、CUDA 依赖及其他 Python 组件的许可文件。
- NASA Earth Observatory 的 2016 Black Marble 夜间地球图像用于静态夜景参考，瓦片来源和 SHA-256 记录在发行包的 `resources/references/blackmarble_2016_500m/manifest.json`。[NASA 数据页](https://science.nasa.gov/earth/earth-observatory/earth-at-night/maps/)。
- GSHHS 陆水遮罩由 Satpy GeoColor 配方引用，按 CC BY 4.0 分发。[上游遮罩记录](https://zenodo.org/records/10076199) · [Satpy](https://github.com/pytroll/satpy)。
- Rayleigh 查找表和传感器光谱响应来自 [PySpectral](https://github.com/pytroll/pyspectral)。气象观测由软件从对应卫星官方公共目录按需获取。

