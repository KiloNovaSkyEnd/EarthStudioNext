namespace EarthStudio.Core;

// Windows calendar controls display local dates; project clock fields are UTC.
public static class UtcCalendar
{
    public static DateTimeOffset ForPicker(DateTimeOffset utc, TimeZoneInfo localZone)
    {
        var noon = new DateTime(utc.Year, utc.Month, utc.Day, 12, 0, 0, DateTimeKind.Unspecified);
        return new DateTimeOffset(noon, localZone.GetUtcOffset(noon));
    }
    public static DateTimeOffset FromPicker(DateTimeOffset calendarValue, TimeSpan utcClock, TimeZoneInfo localZone)
    {
        if (utcClock < TimeSpan.Zero || utcClock >= TimeSpan.FromDays(1)) throw new ArgumentException("请选择有效时刻。");
        var date = TimeZoneInfo.ConvertTime(calendarValue, localZone);
        return new DateTimeOffset(date.Year, date.Month, date.Day, utcClock.Hours, utcClock.Minutes, 0, TimeSpan.Zero);
    }
}
