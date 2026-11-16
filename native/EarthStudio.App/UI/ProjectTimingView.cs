using EarthStudio.Core;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;

namespace EarthStudio.App.UI;

sealed class ProjectTimingView
{
    public UIElement Content { get; }
    public event Action? Changed;
    private readonly ComboBox mode=new(){Header="制作类型",HorizontalAlignment=HorizontalAlignment.Stretch};
    private readonly CalendarDatePicker start=new(){Header="观测日期 · UTC"};
    private readonly TimePicker startTime=new(){ClockIdentifier="24HourClock"};
    private readonly CalendarDatePicker end=new(){Header="结束日期 · UTC"};
    private readonly TimePicker endTime=new(){ClockIdentifier="24HourClock"};
    private readonly ComboBox interval=new(){Header="观测采样间隔"};
    private readonly StackPanel range;
    private readonly TextBlock summary=Ui.Text("",13,true);
    private bool setting;
    public ProjectTimingView()
    {
        mode.Items.Add("单帧图片 · 一个观测时次");mode.Items.Add("延时时间序列 · 一段时间");
        foreach(var value in new[]{10,15,30,60})interval.Items.Add(value+" 分钟");
        range=Ui.Column(end,endTime,interval);
        Content=Ui.Column(mode,start,startTime,range,summary,
            Ui.Text("这里选择卫星观测时间；相机运镜时长和成片帧率在第5步设置。",13,true));
        mode.SelectionChanged+=(_,_)=>Update();interval.SelectionChanged+=(_,_)=>Update();
        start.DateChanged+=(_,_)=>Update();end.DateChanged+=(_,_)=>Update();
        startTime.TimeChanged+=(_,_)=>Update();endTime.TimeChanged+=(_,_)=>Update();
    }
    public void Set(EarthProject value)
    {
        setting=true;mode.SelectedIndex=value.CaptureMode=="single"?0:1;
        start.Date=UtcCalendar.ForPicker(value.StartUtc,TimeZoneInfo.Local);startTime.Time=value.StartUtc.TimeOfDay;
        var finish=value.EndUtc>value.StartUtc?value.EndUtc:value.StartUtc.AddHours(1);
        end.Date=UtcCalendar.ForPicker(finish,TimeZoneInfo.Local);endTime.Time=finish.TimeOfDay;
        interval.SelectedIndex=Array.IndexOf(new[]{10,15,30,60},value.IntervalMinutes);setting=false;Update();
    }
    public EarthProject Read(EarthProject value)
    {
        static DateTimeOffset Utc(CalendarDatePicker date,TimePicker time)=>date.Date is {} day
            ? UtcCalendar.FromPicker(day,time.Time,TimeZoneInfo.Local):throw new ArgumentException("请选择观测日期。");
        var first=Utc(start,startTime);var single=mode.SelectedIndex==0;
        return value with {CaptureMode=single?"single":"sequence",StartUtc=first,EndUtc=single?first:Utc(end,endTime),
            IntervalMinutes=single?10:new[]{10,15,30,60}[Math.Max(0,interval.SelectedIndex)]};
    }
    private void Update()
    {
        if(setting)return;
        var single=mode.SelectedIndex==0;range.Visibility=single?Visibility.Collapsed:Visibility.Visible;
        start.Header=single?"观测日期 · UTC":"开始日期 · UTC";
        try {
            var value=Read(new());var count=single?1:(int)Math.Floor((value.EndUtc-value.StartUtc).TotalMinutes/value.IntervalMinutes)+1;
            summary.Text=count>0?$"计划检查 {count} 个时次；可用观测以第3步目录检查为准。":"结束时间应晚于开始时间。";
        } catch(ArgumentException){summary.Text="请填写完整的UTC日期和时间。";}
        Changed?.Invoke();
    }
}
