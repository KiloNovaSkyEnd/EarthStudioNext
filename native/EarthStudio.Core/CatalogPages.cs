namespace EarthStudio.Core;

public static class CatalogPages
{
    public static int Count(int records)=>Math.Max(1,(records+99)/100);
    public static IEnumerable<int> Indices(int records,int page)
    {
        if(records<0 || page<0 || page>=Count(records))throw new ArgumentOutOfRangeException(nameof(page));
        for(var i=records-1-page*100;i>=Math.Max(0,records-(page+1)*100);i--)yield return i;
    }
}
