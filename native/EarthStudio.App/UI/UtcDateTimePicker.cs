using EarthStudio.Core;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;

namespace EarthStudio.App.UI;

sealed class UtcDateTimePicker
{
    private readonly CalendarDatePicker date;
    private readonly TimePicker time=new(){ClockIdentifier="24HourClock",MinuteIncrement=10};
    public UIElement Content {get;}
    public UtcDateTimePicker(string label,TimeSpan? initialTime=null)
    {
        date=new(){Header=label,PlaceholderText="点击日历选择日期"};
        time.Time=initialTime??TimeSpan.Zero;
        Content=Ui.Column(date,time);
    }
    public DateTimeOffset Read()=>date.Date is {} day
        ? UtcCalendar.FromPicker(day,time.Time,TimeZoneInfo.Local)
        : throw new ArgumentException("请先用日历选择取消范围的起止日期。");
}
