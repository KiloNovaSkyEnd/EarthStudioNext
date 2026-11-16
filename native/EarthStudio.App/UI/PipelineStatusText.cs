using System.Text.Json;

namespace EarthStudio.App.UI;

static class PipelineStatusText
{
    public static string Describe(JsonElement value)
    {
        var phase=value.GetProperty("phase").GetString();
        if(phase is "parallel-running" or "parallel-progress")return Parallel(value);
        var time=value.TryGetProperty("utc",out var utc)?utc.GetString():"";
        var text=phase switch {
            "queue-already-running"=>"制作任务已在运行，正在连接已有进度。",
            "planned"=>"计划已生成，尚未下载。请核对空间和缺档，再开始。",
            "checking-completed"=>$"正在核对已完成素材（{value.GetProperty("checked_completed").GetInt32()}项）；不下载、不重做。",
            "reusing-accepted-scan"=>"复用原项目已验收的正式素材；不重新下载、不重新制作。",
            "hardware-usage"=>Hardware(value.GetProperty("resources")),
            "artist-copy-ready"=>"已另存保留编辑的Blender副本；正在准备其余交付文件。",
            "linking-layered-sequence"=>$"正在共用正式图层（不复制大图）：{value.GetProperty("completed").GetInt32()}/{value.GetProperty("total").GetInt32()}。",
            "copying-layered-sequence"=>"正在复制正式JPG和遮罩到独立素材包，原素材保持只读。",
            "preparing-sequence-preview"=>"正在准备天气显示预览；最终渲染仍使用所选正式分辨率。",
            "building-layered-animation"=>"正在建立原生可编辑天气时钟和分层Blender工程。",
            "sequence-ready"=>"素材包已准备完成，可以进入预览、运镜与Blender。",
            "acquiring"=>"正在准备本时次L1；优先复用已校验缓存。",
            "waiting-resources"=>"资源暂时不足，保持任务并自动复查；条件恢复后自行继续。",
            "recovering-worker"=>value.TryGetProperty("recovery",out var recovery)?$"后台意外退出，{recovery.GetProperty("retry_seconds").GetInt32()}秒后自动恢复第{recovery.GetProperty("attempt").GetInt32()}次；已有成果保留。":$"后台意外退出，{value.GetProperty("retry_seconds").GetInt32()}秒后自动恢复，无需手动继续。",
            "power-guard"=>value.GetProperty("active").GetBoolean()?"生产期间已阻止系统自动休眠；显示器可正常熄屏。":"系统未接受保持唤醒请求，请检查电源状态。",
            "producing"=>"正在制作本时次JPG与必要遮罩。",
            "verifying-and-decoding-inputs"=>"正在校验并解压本时次L1，其他时次尚未下载。",
            "reading-h9-bands"=>"正在读取本时次所需波段。",
            "planning-stock"=>"正在准备GeoColor、夜景与独立灯光图层。",
            "verified-awaiting-user-quality-acceptance"=>"Blender独立重开校验已通过。",
            "committed-awaiting-blender-verification"=>"本时次JPG已提交，接下来进行Blender校验。",
            "computing"=>$"已执行 {value.GetProperty("finished_tasks").GetInt32()} 个计算任务，耗时 {value.GetProperty("seconds").GetDouble():F0} 秒（不是像素完成率）。",
            "verifying"=>"正在生成Blender并独立重新打开校验。",
            "awaiting-quality"=>"首样已生成并校验。请打开检查画质；验收后，后续同档位自动逐时次处理与回收。",
            "awaiting-missing-decision"=>"发现缺档。可勾选保留缺档标记并继续；不会生成虚假观测。",
            "cleaning"=>"正在按已校验清单回收本时次新作业文件。",
            "step-complete"=>"本时次完成，进入下一时次。",
            "paused-space"=>"空间不足，队列暂停。清出空间后可继续，已完成结果保留。",
            "paused-user"=>"已安全暂停：已开始的时次完成校验与清理，预取输入保留，可继续。",
            "paused-resources"=>"可用内存不足，已保留输入和结果；释放其他应用内存后继续。",
            "exporting-full-grid-still"=>"正在导出完整网格的单帧JPG；独立图层继续保留。",
            "still-ready"=>"单帧JPG已交付，可打开成果目录查看。",
            "complete"=>"所选精确扫描制作完成。可点击准备已完成区间，进入运镜与Blender。",
            "verifying-layered-animation"=>"正在独立重开动画工程，检查换帧、分镜时钟与预览切换。",
            "failed-inputs-preserved" or "error"=>"任务暂停，已保留输入和结果："+(value.TryGetProperty("error",out var e)?e.GetString():"请查看日志"),
            "blender-build"=>"正在生成首样/本时次Blender工程。","blender-reopen"=>"正在重新打开验证材质与控制参数。",
            "computing-stock-and-layers"=>"正在计算真实GeoColor与独立地面夜景分层。",
            "encoding-jpeg-and-lossless-masks"=>"正在直接编码JPG与必要的无损遮罩。",
            "projecting-night-500m"=>$"正在准备独立500m夜景贴图：{value.GetProperty("completed").GetInt32()} / {value.GetProperty("total").GetInt32()} 行；完成后复用D盘缓存。",
            _=>"本时次处理中："+phase };
        if(value.TryGetProperty("detail",out var detail)&&detail.TryGetProperty("phase",out var dp))
            text=dp.GetString() switch {
                "inputs-ready"=>$"L1 {detail.GetProperty("completed").GetInt32()}/60；复用 {detail.GetProperty("reused_files").GetInt32()} 个文件，新增下载 {detail.GetProperty("downloaded_bytes").GetInt64()/1048576.0:F1} MB。",
                "download-retrying"=>$"网络暂时不可用，自动重连第 {detail.GetProperty("attempt").GetInt32()} 次；{detail.GetProperty("retry_seconds").GetInt32()} 秒后再试，无需手动继续。",
                "download-recovered"=>"连接已恢复，自动继续下载。",_=>text};
        return string.IsNullOrEmpty(time)?text:time+"\n"+text;
    }
    private static string Parallel(JsonElement value)
    {
        var lines=new List<string>{"流水线运行：下载、计算重叠；逐时次校验与清理。"};
        var actual=value.TryGetProperty("active",out var scans)?scans.EnumerateArray().Count(s=>s.GetProperty("phase").GetString()=="producing"):0;
        var working=value.TryGetProperty("active",out var workingScans)?workingScans.EnumerateArray().ToArray():Array.Empty<JsonElement>();
        var verifying=working.Count(s=>s.GetProperty("phase").GetString() is "verifying" or "verifying-assets");
        var cleaning=working.Count(s=>s.GetProperty("phase").GetString()=="cleaning");
        var waitingVerification=working.Count(s=>s.GetProperty("phase").GetString()=="waiting-verification");
        lines.Add($"正在计算图片：{actual} 张；正在校验：{verifying} 张；正在清理：{cleaning} 张。");
        if(waitingVerification>0)lines.Add($"等待校验：{waitingVerification} 张（已有 JPG）。");
        if(actual==0 && verifying+cleaning+waitingVerification>0)
            lines.Add("当前已有 JPG，正在校验 / 清理；此阶段无需重新计算图片。");
        if(value.TryGetProperty("waiting_reason",out var waiting)&&waiting.ValueKind==JsonValueKind.String)
            lines.Add(waiting.GetString()=="space"?"磁盘余量不足，自动复查并等待空间恢复；已开始任务继续完成。":"后续任务的峰值内存/显存预算暂未通过；已开始任务继续制作，自动复查。");
        if(value.TryGetProperty("compute_slots",out var slots))lines.Add($"同时制作目标：{slots.GetInt32()} 张；独立校验另外排队，启动仍需通过资源检查。");
        if(value.TryGetProperty("concurrency",out var tuning))
        {
            var reason=tuning.GetProperty("reason").GetString() switch {"measured-limit"=>"已达到同素材测试建议上限","ai-resource-admission"=>"AI流水阶段等待内存/显存预算", "memory-or-vram-limit"=>"为后续内存峰值预留，暂缓新增任务","resource-pressure"=>"负载较高，降低后续并发","headroom-ramp"=>"有资源余量，逐步增加","manual-target"=>"按手动目标申请，启动前仍检查资源","cpu-busy"=>"CPU繁忙，保持并发",_=>"等待素材 / 初始化"};
            if(tuning.GetProperty("control").GetString()=="manual"&&actual>=tuning.GetProperty("requested").GetInt32())reason="已达到申请的同时制作数";
            lines.Add($"{(tuning.GetProperty("control").GetString()=="manual"?"手动目标":"自动上限")} {tuning.GetProperty("requested").GetInt32()}张；{reason}。每张内存预算 {tuning.GetProperty("per_scan_budget_bytes").GetDouble()/1073741824:F1} GB。");
            if(tuning.TryGetProperty("ai_gpu_slots",out var gpuSlots)&&gpuSlots.ValueKind==JsonValueKind.Number)
                lines.Add($"AI流水制作：CPU阶段可重叠，GPU推理固定 {gpuSlots.GetInt32()} 路；不会同时加载多份AI模型争抢显存。");
            if(tuning.TryGetProperty("recommended_max_compute",out var recommended)&&recommended.GetInt32()<8)
                lines.Add($"同素材测试建议最多 {recommended.GetInt32()} 张同时制作；手动模式可覆盖，仍检查实际资源。");
            if(tuning.TryGetProperty("verification_budget_bytes",out var verification))
                lines.Add($"独立校验内存预算 {verification.GetDouble()/1073741824:F1} GB；当前系统可用 {tuning.GetProperty("available_bytes").GetDouble()/1073741824:F1} GB。");
        }
        if(value.TryGetProperty("active",out var active))
        {
        var queued=active.EnumerateArray().Where(s=>s.GetProperty("phase").GetString() is "waiting-download" or "retry-wait").ToArray();
        foreach(var scan in active.EnumerateArray().Where(s=>s.GetProperty("phase").GetString() is not ("waiting-download" or "retry-wait")))
        {
            var label=scan.GetProperty("phase").GetString() switch {"waiting-network"=>"网络暂不可用，持续自动重连；恢复后自行继续","retry-wait"=>"等待失败时次重试（未计入实际并发）","waiting-download"=>"等待下载槽位","acquiring"=>"下载/复用L1","ready"=>"预取完成，等待处理","producing"=>"计算JPG与图层","waiting-verification"=>"等待校验","verifying"=>"Blender独立校验","verifying-assets"=>"完整图片与模板依赖校验","cleaning"=>"清理本时次L1/中间文件","failed"=>"失败，保留输入",_=>"处理中"};
            if(scan.TryGetProperty("retry",out var retry)&&scan.GetProperty("phase").GetString()=="waiting-network")
                label+=$"（第 {retry.GetProperty("attempt").GetInt32()} 次，间隔 {retry.GetProperty("retry_seconds").GetInt32()} 秒）";
            lines.Add(scan.GetProperty("utc").GetString()+" · "+label);
        }
        var waitingDownload=queued.Count(s=>s.GetProperty("phase").GetString()=="waiting-download");
        var waitingRetry=queued.Length-waitingDownload;
        if(waitingDownload>0)lines.Add($"排队等待检查 / 复用素材：{waitingDownload} 个时次。");
        if(waitingRetry>0)lines.Add($"等待失败重试：{waitingRetry} 个时次（未计入实际并发）。");
        }
        return string.Join("\n",lines);
    }
    private static string Hardware(JsonElement r)
    {
        var cpu=r.GetProperty("process_cpu_core_percent").GetDouble()/Environment.ProcessorCount;
        var ram=r.GetProperty("process_rss_bytes").GetInt64()/1073741824.0;
        var available=r.GetProperty("system_available_bytes").GetInt64()/1073741824.0;
        var gpu=r.GetProperty("gpu_fusion");var calls=gpu.TryGetProperty("calls",out var c)?c.GetInt64():0;
        return $"当前计算资源：进程CPU约 {cpu:F1}%（整机比例），内存 {ram:F2} GB；系统可用 {available:F1} GB；CUDA算子已调用 {calls} 次。";
    }
}
