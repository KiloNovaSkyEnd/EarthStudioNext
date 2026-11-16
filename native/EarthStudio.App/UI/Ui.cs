using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using Windows.UI;

namespace EarthStudio.App.UI;

static class Ui
{
    public static TextBlock Text(string text, double size = 14, bool muted = false) => new()
    {
        Text = text, FontSize = size, TextWrapping = TextWrapping.Wrap,
        Foreground = new SolidColorBrush(muted ? Color.FromArgb(255, 150, 166, 184) : Color.FromArgb(255, 235, 241, 249))
    };
    public static Button Button(string text, Action clicked, bool accent = false)
    {
        var result = new Button { Content = text, Padding = new Thickness(16, 9, 16, 9) };
        if (accent) result.Style = (Style)Application.Current.Resources["AccentButtonStyle"];
        result.Click += (_, _) => clicked();
        return result;
    }
    public static Border Card(UIElement child, Thickness? padding = null) => new()
    {
        Child = child, Padding = padding ?? new Thickness(20), CornerRadius = new CornerRadius(12),
        Background = new SolidColorBrush(Color.FromArgb(255, 24, 32, 44)),
        BorderBrush = new SolidColorBrush(Color.FromArgb(255, 43, 55, 72)), BorderThickness = new Thickness(1)
    };
    public static StackPanel Column(params UIElement[] children)
    {
        var panel = new StackPanel { Spacing = 12 };
        foreach (var child in children) panel.Children.Add(child);
        return panel;
    }
    public static ScrollViewer Scroll(UIElement content) => new() { Content = content, Padding = new Thickness(24), VerticalScrollBarVisibility = ScrollBarVisibility.Auto };
}
