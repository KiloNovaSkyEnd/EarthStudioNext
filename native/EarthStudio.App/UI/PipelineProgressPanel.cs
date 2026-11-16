using System.Text.Json;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;

namespace EarthStudio.App.UI;

sealed class PipelineProgressPanel
{
    public UIElement Content {get;}
    private readonly TextBlock heading=Ui.Text("尚未开始",22);
    private readonly ProgressBar bar=new(){Minimum=0,Maximum=100,Height=6};
    private readonly TextBlock science=Ui.Text("0",26),download=Ui.Text("0",26),verify=Ui.Text("0",26),queue=Ui.Text("0",26);
    private readonly TextBlock message=Ui.Text("生成计划后开始制作。",14,true);
    public PipelineProgressPanel()
    {
        var metrics=new Grid{ColumnSpacing=12};
        var cells=new[]{("科学计算",science),("下载",download),("校验 / 清理",verify),("排队",queue)};
        for(var i=0;i<cells.Length;i++)
        {
            metrics.ColumnDefinitions.Add(new ColumnDefinition{Width=new GridLength(1,GridUnitType.Star)});
            var cell=Ui.Column(Ui.Text(cells[i].Item1,13,true),cells[i].Item2);Grid.SetColumn(cell,i);metrics.Children.Add(cell);
        }
        message.Height=48;message.MaxLines=2;message.TextTrimming=TextTrimming.CharacterEllipsis;
        Content=new Border{Height=200,Child=Ui.Column(heading,bar,metrics,message)};
    }
    public void Update(JsonElement state,int completed,int total)
    {
        heading.Text=$"已完成 {completed:N0} / {total:N0}";
        bar.Value=total>0?100.0*completed/total:0;
        var phase=state.TryGetProperty("phase",out var p)?p.GetString():"";
        var active=phase is "parallel-running" or "parallel-progress" && state.TryGetProperty("active",out var tasks)?tasks.EnumerateArray().ToArray():Array.Empty<JsonElement>();
        int Count(params string[] phases)=>active.Count(s=>phases.Contains(s.GetProperty("phase").GetString()));
        var computing=Count("producing");var checking=Count("verifying","verifying-assets","cleaning");
        science.Text=computing.ToString();download.Text=Count("acquiring").ToString();verify.Text=checking.ToString();
        queue.Text=Count("ready","waiting-download","waiting-verification","retry-wait","waiting-network").ToString();
        message.Text=phase switch
        {
            "paused-user"=>"已暂停，点击继续可恢复。",
            "complete"=>"制作完成，可以准备动画素材。",
            "checking-completed"=>$"正在核对已有成果：{(state.TryGetProperty("checked_completed",out var checkedCount)?checkedCount.GetInt32():0):N0} / {completed:N0}；完成后开始新任务。",
            "parallel-running" or "parallel-progress" when computing>0=>$"科学计算 {computing} 张进行中。",
            "parallel-running" or "parallel-progress" when checking>0||Count("waiting-verification")>0=>"科学计算暂未运行；正在验收已有图片。",
            "parallel-running" or "parallel-progress"=>"等待素材或处理位置；科学计算暂未运行。",
            _=>PipelineStatusText.Describe(state).Split('\n')[0]
        };
    }
    public void Clear(){heading.Text="尚未开始";bar.Value=0;science.Text=download.Text=verify.Text=queue.Text="0";message.Text="生成计划后开始制作。";}
}
