using EarthStudio.Core;
using System.Text.Json;
using Microsoft.UI.Xaml.Controls;

namespace EarthStudio.App;

sealed partial class MainWindow
{
    private void ConfigureNavigation()
    {
        foreach(var item in new[]{("1 数据账户","accounts",Symbol.Contact),("2 制作内容 · 单帧 / 序列","project",Symbol.World),
            ("3 数据检查","tasks",Symbol.Download),("4 下载与素材制作","pipeline",Symbol.Save),("5 预览、运镜与Blender","cesium",Symbol.World)})
            navigation.MenuItems.Add(new NavigationViewItem{Content=item.Item1,Tag=item.Item2,Icon=new SymbolIcon(item.Item3)});
        var advanced=new NavigationViewItem{Content="高级工具与开发验证",Icon=new SymbolIcon(Symbol.Setting),SelectsOnInvoked=false};
        foreach(var item in new[]{("本机已有L1试制","production"),("历史测试工作区","validation"),("能力与开发进度","upgrade")})
            advanced.MenuItems.Add(new NavigationViewItem{Content=item.Item1,Tag=item.Item2});
        navigation.MenuItems.Add(advanced);
    }
    private void RefreshWorkflow()
    {
        try
        {
            var value=project.ReadProject();var checkedSpec=catalogSnapshot??inventoryProject;tasks.SetSelectionChanged(checkedSpec!=null&&!WorkflowRules.SameCatalog(value,checkedSpec),catalogSnapshot!=null);var blocker=WorkflowRules.ProductionBlocker(value);
            var valid=lastInventory!=null && inventoryProject!=null && WorkflowRules.SameProduction(value,inventoryProject);
            pipeline.SetReadiness(valid && blocker==null,blocker ?? (valid?"目录已检查，核对计划后开始制作。":"请先完成第3步；修改设置后重新检查，已有时次会自动复用。"));
            if(queues.QueueDirectory!=null)
            {
                var frozen=queues.Read("plan.json").GetProperty("project").Deserialize<EarthProject>();
                pipeline.SetQueueMatch(frozen!=null && WorkflowRules.SameProduction(value,frozen));
            }
        }
        catch(ArgumentException error){pipeline.SetReadiness(false,error.Message);pipeline.SetQueueMatch(false);}
    }
    private static IEnumerable<NavigationViewItem> NavigationItems(IEnumerable<object> items)
    {
        foreach(var item in items.OfType<NavigationViewItem>())
        {yield return item;foreach(var child in NavigationItems(item.MenuItems))yield return child;}
    }
}
