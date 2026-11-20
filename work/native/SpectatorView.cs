using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Media.Animation;
using System.Windows.Shapes;
using System.Windows.Threading;

namespace YgoKi
{
    sealed class WatchSlot
    {
        public string Name { get; set; }
        public string Stats { get; set; }
        public CardRow Art { get; set; }
    }

    sealed class WatchChainLink
    {
        public WatchChainLink(Dictionary<string, object> data)
        {
            Number = "#" + data["number"];
            Title = data.Text("player") + " · " + data.Text("name") + " (" + data.Text("zone") + ")";
            Effect = data.Text("effect") ?? "Effekttext fehlt";
            string state = data.Text("state") ?? "offen";
            State = data.Text("state_label") ?? state;
            object targetsValue = data.Get("targets");
            var targets = targetsValue as object[];
            Target = targets == null || targets.Length == 0 ? "kein Ziel" :
                "Ziel: " + String.Join(", ", targets.Select(Json.Object).Select(item => item.Text("name")));
            int controller = data.Get("controller") == null ? 0 : Convert.ToInt32(data["controller"]);
            PlayerBrush = new SolidColorBrush(controller == 0 ? Color.FromRgb(0x9E, 0xC5, 0xFF)
                                                               : Color.FromRgb(0xFF, 0xC1, 0x9A));
            if (state == "negiert")
            {
                StateBrush = new SolidColorBrush(Color.FromRgb(0xFF, 0x9A, 0xA8));
                StateBackground = new SolidColorBrush(Color.FromRgb(0x4A, 0x1B, 0x26));
                Border = StateBrush;
            }
            else if (state == "annulliert")
            {
                StateBrush = new SolidColorBrush(Color.FromRgb(0xFF, 0xC1, 0x73));
                StateBackground = new SolidColorBrush(Color.FromRgb(0x43, 0x2C, 0x16));
                Border = StateBrush;
            }
            else if (state == "aufgeloest")
            {
                StateBrush = new SolidColorBrush(Color.FromRgb(0xA8, 0xE6, 0xB4));
                StateBackground = new SolidColorBrush(Color.FromRgb(0x1B, 0x3A, 0x26));
                Border = new SolidColorBrush(Color.FromRgb(0x3E, 0x80, 0x52));
            }
            else if (state == "loest_auf")
            {
                StateBrush = new SolidColorBrush(Color.FromRgb(0xD5, 0xB8, 0xFF));
                StateBackground = new SolidColorBrush(Color.FromRgb(0x2D, 0x24, 0x48));
                Border = StateBrush;
            }
            else
            {
                StateBrush = new SolidColorBrush(Color.FromRgb(0x9E, 0xC5, 0xFF));
                StateBackground = new SolidColorBrush(Color.FromRgb(0x1A, 0x2A, 0x45));
                Border = new SolidColorBrush(Color.FromRgb(0x3E, 0x67, 0x9A));
            }
        }

        public string Number { get; private set; }
        public string Title { get; private set; }
        public string Effect { get; private set; }
        public string Target { get; private set; }
        public string State { get; private set; }
        public Brush PlayerBrush { get; private set; }
        public Brush StateBrush { get; private set; }
        public Brush StateBackground { get; private set; }
        public Brush Border { get; private set; }
    }

    sealed partial class Desktop
    {
        private readonly DispatcherTimer watchTimer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(120) };
        private readonly Dictionary<long, CardRow> watchArt = new Dictionary<long, CardRow>();
        private readonly Dictionary<string, object[]> watchPiles = new Dictionary<string, object[]>();
        private readonly Dictionary<string, ContentControl> fieldSlots = new Dictionary<string, ContentControl>();
        private readonly Dictionary<string, TextBlock> fieldMarks = new Dictionary<string, TextBlock>();
        private readonly Dictionary<string, Border> fieldFlash = new Dictionary<string, Border>();
        private static readonly string[] PileKinds = { "Deck", "Extra", "Grave", "Banished" };
        private static readonly string[] PileLabels = { "Deck", "Extra Deck", "Friedhof", "Verbannt" };
        private bool watchRunning, watchPaused, watchPolling, watchWaiting;
        private bool watchChainEnabled = true;
        private bool watchAnimationWait;
        private int watchSerial, watchGeneration;
        private int watchChainGeneration;
        private DateTime watchNextAfter;
        private DateTime watchAnimationUntil = DateTime.MinValue;
        private ItemsControl ChainList { get { return Find<ItemsControl>("WatchChainLinks"); } }
        private Border ChainPanel { get { return Find<Border>("WatchChainPanel"); } }
        private TextBlock ChainTitle { get { return Text("WatchChainTitle"); } }
        private Canvas FxLayer { get { return Find<Canvas>("WatchFxLayer"); } }
        private static readonly int[] WatchDelays = { 900, 420, 210, 85 };
        private static readonly string[] WatchAnimationModes = { "An", "Reduziert", "Aus" };
        private static readonly string[] WatchPhases = { "Draw", "Standby", "Main1", "Battle", "Main2", "End" };
        private static readonly int[] WatchPhaseMasks = { 1, 2, 4, 248, 256, 512 };

        private void SetupWatcher()
        {
            Combo("WatchFormat").ItemsSource = new[] { "Vorschau", "TCG", "OCG" };
            Combo("WatchFormat").SelectedIndex = 0;
            Combo("WatchSpeed").ItemsSource = new[] { "Langsam", "Normal", "Schnell", "Sehr schnell" };
            Combo("WatchSpeed").SelectedIndex = 1;
            Combo("WatchAnimations").ItemsSource = WatchAnimationModes;
            Combo("WatchAnimations").SelectedIndex = 0;
            Find<CheckBox>("WatchChains").Checked += delegate { SetChainVisible(true); };
            Find<CheckBox>("WatchChains").Unchecked += delegate { SetChainVisible(false); };
            OnClickAsync("WatchStart", StartWatch);
            OnClick("WatchPause", () => PauseWatch(!watchPaused));
            OnClickAsync("WatchNext", AdvanceWatch);
            OnClickAsync("WatchStop", StopWatch);
            watchTimer.Tick += async delegate { await Guard(PollWatch); };
            BuildField();
            foreach (string side in new[] { "Top", "Bottom" })
            {
                Find<ItemsControl>("Watch" + side + "Hand").MouseLeftButtonDown += WatchPicture;
                for (int index = 0; index < PileKinds.Length; index++)
                {
                    string kind = PileKinds[index], label = PileLabels[index];
                    OnClick("Watch" + side + kind, () => ShowWatchPile(side, kind, label));
                }
            }
            ResetBoard();
        }

        private void WatchLibrary()
        {
            var left = Combo("WatchLeft").SelectedItem as DeckRef;
            var right = Combo("WatchRight").SelectedItem as DeckRef;
            Combo("WatchLeft").ItemsSource = library;
            Combo("WatchRight").ItemsSource = library;
            Combo("WatchLeft").SelectedItem = (left == null ? null : MatchDeck(left.Name, left.Source))
                ?? MatchDeck("HERO", "original") ?? library.FirstOrDefault();
            Combo("WatchRight").SelectedItem = (right == null ? null : MatchDeck(right.Name, right.Source))
                ?? MatchDeck("D Link", "original") ?? library.Skip(1).FirstOrDefault() ?? library.FirstOrDefault();
        }

        private void ResetBoard()
        {
            Text("WatchTopName").Text = "Deck B";
            Text("WatchBottomName").Text = "Deck A";
            Text("WatchTopInfo").Text = Text("WatchBottomInfo").Text = "";
            watchPiles.Clear();
            MarkPhase(0);
            foreach (var key in fieldSlots.Keys.ToArray()) SetZone(key, null, false, null);
            Text("WatchAction").Text = "Noch keine Aktion";
            Text("WatchAction").Foreground = (Brush)window.FindResource("Muted");
            ChainList.ItemsSource = null;
            ChainTitle.Text = "Kette";
            ChainPanel.Visibility = Visibility.Collapsed;
            watchChainGeneration++;
            FxLayer.Children.Clear();
            watchAnimationUntil = DateTime.MinValue;
            foreach (string side in new[] { "Top", "Bottom" })
            {
                for (int index = 0; index < PileKinds.Length; index++) SetPile(side, PileKinds[index], PileLabels[index], null);
                Find<ItemsControl>("Watch" + side + "Hand").ItemsSource = null;
                Text("Watch" + side + "HandLabel").Text = "Hand";
            }
            Find<ListBox>("WatchLog").Items.Clear();
        }

        private void WatchButtons()
        {
            Button("WatchStart").IsEnabled = !watchRunning;
            Button("WatchPause").IsEnabled = watchRunning;
            Button("WatchNext").IsEnabled = watchRunning && watchPaused && watchWaiting && !watchAnimationWait;
            Button("WatchStop").IsEnabled = watchRunning;
            Button("WatchPause").Content = watchPaused ? "Fortsetzen" : "Pause";
        }

        private async Task StartWatch()
        {
            if (watchRunning || !ready) return;
            var left = Combo("WatchLeft").SelectedItem as DeckRef;
            var right = Combo("WatchRight").SelectedItem as DeckRef;
            if (left == null || right == null) throw new InvalidOperationException("Wähle zwei Decks für das Duell.");
            ResetBoard();
            watchArt.Clear();
            int generation = ++watchGeneration;
            watchSerial = 0;
            watchWaiting = watchPaused = false;
            watchRunning = true;
            WatchButtons();
            Text("WatchState").Text = "Decks werden geprüft …";
            Text("WatchError").Visibility = Visibility.Collapsed;
            try
            {
                await bridge.Call("watch_start", Json.Fields("left", left.Data, "right", right.Data, "format", Choice("WatchFormat")));
                if (!watchRunning || generation != watchGeneration) return;
                watchTimer.Start();
                await PollWatch();
            }
            catch
            {
                if (generation != watchGeneration) return;
                watchTimer.Stop();
                watchRunning = false;
                WatchButtons();
                Text("WatchState").Text = "Duell konnte nicht gestartet werden.";
                throw;
            }
        }

        private void PauseWatch(bool pause)
        {
            if (!watchRunning) return;
            watchPaused = pause;
            WatchButtons();
        }

        private async Task AdvanceWatch()
        {
            if (!watchWaiting || watchPolling || watchAnimationWait) return;
            watchAnimationWait = true;
            WatchButtons();
            try
            {
                // Einzelschritt und Pause dürfen die nächste Aktion erst nach der laufenden Animation anfordern.
                int wait = (int)Math.Max(0, (watchAnimationUntil - DateTime.UtcNow).TotalMilliseconds);
                if (wait > 0) await Task.Delay(wait);
                if (!watchRunning || !watchWaiting) return;
                watchPolling = true;
                watchWaiting = false;
                WatchButtons();
                try { await bridge.Call("watch_next", Json.Fields("serial", watchSerial)); }
                finally { watchPolling = false; }
            }
            finally
            {
                watchAnimationWait = false;
                WatchButtons();
            }
        }

        private async Task StopWatch()
        {
            if (!watchRunning) return;
            int generation = ++watchGeneration;
            watchTimer.Stop();
            watchRunning = watchWaiting = false;
            WatchButtons();
            await bridge.Call("watch_stop");
            if (generation == watchGeneration) Text("WatchState").Text = "Duell beendet.";
        }

        private async Task PollWatch()
        {
            if (!watchRunning || watchPolling) return;
            int generation = watchGeneration;
            watchPolling = true;
            try
            {
                var frame = Json.Object(await bridge.Call("watch_state"));
                if (!watchRunning || generation != watchGeneration) return;
                int serial = Convert.ToInt32(frame["serial"]);
                watchWaiting = Object.Equals(frame["waiting"], true);
                string status = frame.Text("status");
                if (serial != watchSerial && frame.Get("players") != null)
                {
                    int animation = RenderWatch(frame);
                    int delay = WatchDelays[Math.Max(0, Combo("WatchSpeed").SelectedIndex)];
                    watchNextAfter = DateTime.UtcNow.AddMilliseconds(Math.Max(delay, animation + 80));
                }
                watchSerial = serial;
                if (status == "error" || status == "done" || status == "cancelled")
                {
                    watchTimer.Stop();
                    watchRunning = false;
                    if (status == "error")
                    {
                        Text("WatchState").Text = "Duellfehler";
                        Text("WatchError").Text = frame.Text("error");
                        Text("WatchError").Visibility = Visibility.Visible;
                    }
                    else if (status == "done")
                        Text("WatchState").Text = frame.Text("winner") == null ? "Unentschieden" : "Gewonnen · " + frame.Text("winner");
                }
                WatchButtons();
            }
            finally { watchPolling = false; }
            if (watchRunning && !watchPaused && DateTime.UtcNow >= watchNextAfter) await AdvanceWatch();
        }

        private int RenderWatch(Dictionary<string, object> frame)
        {
            var players = frame.Array("players").Select(Json.Object).ToArray();
            int active = Convert.ToInt32(frame["active"]);
            MarkPhase(Convert.ToInt32(frame["phase_id"]));
            Text("WatchState").Text = "Zug " + frame["turn"] + " · " + frame.Text("phase")
                + (active >= 0 && active < players.Length ? " · " + players[active].Text("name") : "");
            for (int side = 0; side < players.Length; side++)
            {
                string panel = side == 0 ? "Bottom" : "Top";
                var player = players[side];
                Text("Watch" + panel + "Name").Text = player.Text("name") + " · " + player["lp"] + " LP";
                Text("Watch" + panel + "Info").Text = player.Text("strategy");
                var hand = player.Array("hand_cards");
                Text("Watch" + panel + "HandLabel").Text = "Hand · " + hand.Length;
                Find<ItemsControl>("Watch" + panel + "Hand").ItemsSource = hand.Select(value => WatchCard(value, false)).ToArray();
                SetPile(panel, "Deck", "Deck", player.Array("deck_cards"));
                SetPile(panel, "Extra", "Extra Deck", player.Array("extra_cards"));
                SetPile(panel, "Grave", "Friedhof", player.Array("grave_cards"));
                SetPile(panel, "Banished", "Verbannt", player.Array("banished_cards"));
                var monsters = player.Array("monsters") ?? new object[0];
                var spells = player.Array("spells") ?? new object[0];
                for (int zone = 0; zone < 5; zone++)
                    SetZone(panel + "M" + zone, zone < monsters.Length ? monsters[zone] : null, true, null);
                for (int zone = 0; zone < 6; zone++)
                    SetZone(panel + "S" + zone, zone < spells.Length ? spells[zone] : null, false, null);
            }
            // Extra-Monsterzonen gehören keinem Spieler fest: links/rechts aus Sicht des unteren Spielers
            var extra = new object[2];
            var owner = new string[2];
            for (int side = 0; side < players.Length; side++)
            {
                var monsters = players[side].Array("monsters") ?? new object[0];
                for (int zone = 0; zone < 2; zone++)
                {
                    if (5 + zone >= monsters.Length || monsters[5 + zone] == null) continue;
                    int place = side == 0 ? zone : 1 - zone;
                    extra[place] = monsters[5 + zone];
                    owner[place] = side == 0 ? "unten" : "oben";
                }
            }
            for (int place = 0; place < 2; place++) SetZone("XE" + place, extra[place], true, owner[place]);
            int animation = AnimateActions(frame.Array("actions"));
            RenderChain(frame);
            var log = Find<ListBox>("WatchLog");
            foreach (object entry in frame.Array("events"))
            {
                if (log.Items.Count == 360) log.Items.RemoveAt(0);
                log.Items.Add(entry);
            }
            if (log.Items.Count > 0) log.ScrollIntoView(log.Items[log.Items.Count - 1]);
            return animation;
        }

        private void SetChainVisible(bool enabled)
        {
            watchChainEnabled = enabled;
            if (!enabled)
            {
                watchChainGeneration++;
                ChainPanel.Visibility = Visibility.Collapsed;
                return;
            }
            if (ChainList.Items.Count > 0) ChainPanel.Visibility = Visibility.Visible;
        }

        private void RenderChain(Dictionary<string, object> frame)
        {
            if (!watchChainEnabled) return;
            object raw = frame.Get("chain");
            if (raw == null) return;
            var chain = Json.Object(raw);
            int count = chain.Get("count") == null ? 0 : Convert.ToInt32(chain["count"]);
            if (count <= 0) return;
            var links = (chain.Get("links") as object[] ?? new object[0])
                .Select(Json.Object).Select(data => new WatchChainLink(data)).ToArray();
            ChainList.ItemsSource = links;
            ChainTitle.Text = chain.Text("title") ?? "Kette";
            ChainPanel.BeginAnimation(UIElement.OpacityProperty, null);
            ChainPanel.Opacity = 1;
            ChainPanel.Visibility = Visibility.Visible;
            int generation = ++watchChainGeneration;
            bool open = Object.Equals(chain.Get("open"), true);
            if (open)
            {
                // offen: bleibt stehen, bis der naechste Frame kommt
            }
            else
            {
                HideClosedChain(generation);
            }
        }

        private async void HideClosedChain(int generation)
        {
            await Task.Delay(1300);
            // Im Einzelschritt bleibt der Stapel stehen; erst der nächste Schritt blendet ihn aus.
            if (generation != watchChainGeneration || !watchRunning || watchPaused) return;
            var fade = new DoubleAnimation(1.0, 0.0, new Duration(TimeSpan.FromMilliseconds(260)));
            fade.Completed += delegate
            {
                if (generation == watchChainGeneration)
                {
                    ChainPanel.Visibility = Visibility.Collapsed;
                    ChainPanel.Opacity = 1;
                    ChainList.ItemsSource = null;
                }
            };
            ChainPanel.BeginAnimation(UIElement.OpacityProperty, fade);
        }

        private void MarkPhase(int phase)
        {
            for (int index = 0; index < WatchPhases.Length; index++)
            {
                var chip = Text("WatchPhase" + WatchPhases[index]);
                var style = (Style)window.FindResource((phase & WatchPhaseMasks[index]) != 0
                    ? "WatchPhaseActive" : "WatchPhaseChip");
                if (chip.Style != style) chip.Style = style;
            }
        }

        private static Color ActionColor(string kind, Dictionary<string, object> action = null)
        {
            switch (kind)
            {
                case "summon": return Color.FromRgb(0xF2, 0xC1, 0x4E);    // Normalbeschwörung: gold
                case "spsummon": return SpecialColor(action == null ? null : action.Text("special_kind"));
                case "flip": return Color.FromRgb(0xE8, 0xD4, 0x8A);
                case "activate": return Color.FromRgb(0x4E, 0xA8, 0xFF);   // Aktivierung/Kette: blau
                case "set": return Color.FromRgb(0x9A, 0xA7, 0xBD);        // Setzen: grau
                case "attack": return Color.FromRgb(0xFF, 0x54, 0x70);     // Angriff: rot
                case "target": return Color.FromRgb(0xFF, 0xB3, 0xC0);
                case "destroy": return Color.FromRgb(0xFF, 0x54, 0x70);     // Zerstört: rot
                case "banish": return Color.FromRgb(0xB9, 0x8C, 0xFF);      // Verbannt: violett
                case "hand": return Color.FromRgb(0x7E, 0xE0, 0xA3);        // Auf die Hand: grün
                case "material": return Color.FromRgb(0xC9, 0xB8, 0xFF);
                default: return Color.FromRgb(0xAB, 0xB6, 0xCC);
            }
        }

        private static Color SpecialColor(string kind)
        {
            switch (kind)
            {
                case "fusion": return Color.FromRgb(0xC9, 0x83, 0xFF);
                case "synchro": return Color.FromRgb(0x9E, 0xFF, 0xCB);
                case "xyz": return Color.FromRgb(0xFF, 0xD3, 0x6E);
                case "link": return Color.FromRgb(0x62, 0xB6, 0xFF);
                case "ritual": return Color.FromRgb(0x6F, 0xE7, 0xE7);
                case "pendulum": return Color.FromRgb(0xFF, 0x8F, 0xD0);
                default: return Color.FromRgb(0xFF, 0x8A, 0x3D);
            }
        }

        private static string SpecialLabel(string kind)
        {
            switch (kind)
            {
                case "fusion": return "FUSION";
                case "synchro": return "SYNCHRO";
                case "xyz": return "XYZ";
                case "link": return "LINK";
                case "ritual": return "RITUAL";
                case "pendulum": return "PENDEL";
                default: return "SPEZIAL";
            }
        }

        private string ActionKey(Dictionary<string, object> action)
        {
            if (action.Get("player") == null || action.Get("loc") == null || action.Get("seq") == null) return null;
            return KeyFor(Convert.ToInt32(action["player"]), Convert.ToInt32(action["loc"]),
                          Convert.ToInt32(action["seq"]));
        }

        private string KeyFor(int player, int location, int sequence)
        {
            string side = player == 0 ? "Bottom" : "Top";
            if (location == 4)
            {
                if (sequence >= 5) return "XE" + (player == 0 ? sequence - 5 : 1 - (sequence - 5));
                return side + "M" + sequence;
            }
            if (location == 8 && sequence <= 5) return side + "S" + sequence;
            if (location == 0x10) return side + "Grave";
            if (location == 0x20) return side + "Banished";
            if (location == 0x02) return side + "Hand";
            if (location == 0x01) return side + "Deck";
            if (location == 0x40) return side + "Extra";
            return null;
        }

        private string MaterialKey(Dictionary<string, object> material)
        {
            return KeyFor(Convert.ToInt32(material["player"]), Convert.ToInt32(material["loc"]),
                            Convert.ToInt32(material["seq"]));
        }

        private string MaterialDestination(Dictionary<string, object> material, string summonKey)
        {
            int location = material.Get("to_loc") == null ? 0x10 : Convert.ToInt32(material["to_loc"]);
            if (location == 0x80) return summonKey;
            return KeyFor(Convert.ToInt32(material["to_player"]), location,
                          Convert.ToInt32(material["to_seq"]));
        }

        private int AnimationLevel()
        {
            int selected = Combo("WatchAnimations").SelectedIndex;
            if (selected >= 2) return 0;
            if (selected == 1 || Combo("WatchSpeed").SelectedIndex >= 3) return 1;
            return 2;
        }

        private static int AnimationDuration(int level)
        {
            return level <= 0 ? 0 : (level == 1 ? 300 : 520);
        }

        private static IEasingFunction EaseOut()
        {
            return new QuadraticEase { EasingMode = EasingMode.EaseOut };
        }

        private FrameworkElement ElementFor(string key)
        {
            if (String.IsNullOrEmpty(key)) return null;
            ContentControl slot;
            if (fieldSlots.TryGetValue(key, out slot)) return slot;
            if (key.EndsWith("Hand")) return Find<ItemsControl>("Watch" + key);
            if (key.EndsWith("Grave") || key.EndsWith("Banished") || key.EndsWith("Deck") || key.EndsWith("Extra"))
                return Find<Button>("Watch" + key);
            return null;
        }

        private Point? CenterOf(string key)
        {
            var element = ElementFor(key);
            if (element == null || element.ActualWidth <= 0 || element.ActualHeight <= 0) return null;
            try
            {
                return element.TranslatePoint(new Point(element.ActualWidth / 2, element.ActualHeight / 2), FxLayer);
            }
            catch (InvalidOperationException) { return null; }
        }

        private Point FxCenter()
        {
            return new Point(Math.Max(1, FxLayer.ActualWidth) / 2, Math.Max(1, FxLayer.ActualHeight) / 2);
        }

        private void Place(UIElement element, Point point, double width, double height)
        {
            Canvas.SetLeft(element, point.X - width / 2);
            Canvas.SetTop(element, point.Y - height / 2);
            FxLayer.Children.Add(element);
        }

        private Border MakeGhost(string name, Color color, double width, double height)
        {
            var ghost = new Border
            {
                Width = width, Height = height, CornerRadius = new CornerRadius(5),
                Background = new SolidColorBrush(Color.FromArgb(0xE6, 0x12, 0x18, 0x26)),
                BorderBrush = new SolidColorBrush(color), BorderThickness = new Thickness(2),
                Opacity = 0, RenderTransform = new ScaleTransform(1, 1),
                RenderTransformOrigin = new Point(0.5, 0.5)
            };
            ghost.Child = new TextBlock
            {
                Text = name, Foreground = new SolidColorBrush(color), FontSize = 9, FontWeight = FontWeights.SemiBold,
                TextWrapping = TextWrapping.Wrap, TextAlignment = TextAlignment.Center,
                HorizontalAlignment = HorizontalAlignment.Center, VerticalAlignment = VerticalAlignment.Center,
                Margin = new Thickness(3)
            };
            return ghost;
        }

        private void Fade(UIElement element, double from, double to, int duration, int delay = 0)
        {
            var fade = new DoubleAnimation(from, to, new Duration(TimeSpan.FromMilliseconds(duration)))
            { BeginTime = TimeSpan.FromMilliseconds(delay), EasingFunction = EaseOut() };
            element.BeginAnimation(UIElement.OpacityProperty, fade);
        }

        private void Move(UIElement element, DependencyProperty property, double from, double to, int duration,
                         int delay = 0)
        {
            var move = new DoubleAnimation(from, to, new Duration(TimeSpan.FromMilliseconds(duration)))
            { BeginTime = TimeSpan.FromMilliseconds(delay), EasingFunction = EaseOut() };
            element.BeginAnimation(property, move);
        }

        private void Scale(ScaleTransform scale, double from, double to, int duration, int delay = 0)
        {
            var x = new DoubleAnimation(from, to, new Duration(TimeSpan.FromMilliseconds(duration)))
            { BeginTime = TimeSpan.FromMilliseconds(delay), EasingFunction = EaseOut() };
            var y = new DoubleAnimation(from, to, new Duration(TimeSpan.FromMilliseconds(duration)))
            { BeginTime = TimeSpan.FromMilliseconds(delay), EasingFunction = EaseOut() };
            scale.BeginAnimation(ScaleTransform.ScaleXProperty, x);
            scale.BeginAnimation(ScaleTransform.ScaleYProperty, y);
        }

        private void Ring(Point center, Color color, int duration, double width = 96, double height = 66)
        {
            var ring = new Border
            {
                Width = width, Height = height, CornerRadius = new CornerRadius(10),
                BorderBrush = new SolidColorBrush(color), BorderThickness = new Thickness(2),
                Opacity = 0.9, RenderTransform = new ScaleTransform(0.5, 0.5),
                RenderTransformOrigin = new Point(0.5, 0.5)
            };
            Place(ring, center, width, height);
            Scale((ScaleTransform)ring.RenderTransform, 0.5, 1.65, duration);
            Fade(ring, 0.9, 0, duration);
        }

        private void Badge(Point center, string text, Color color, int duration)
        {
            var badge = new Border
            {
                Padding = new Thickness(7, 3, 7, 3), CornerRadius = new CornerRadius(4),
                Background = new SolidColorBrush(Color.FromArgb(0xD8, 0x0C, 0x10, 0x18)),
                BorderBrush = new SolidColorBrush(color), BorderThickness = new Thickness(1),
                Opacity = 0.95
            };
            var label = new TextBlock { Text = text, Foreground = new SolidColorBrush(color), FontSize = 10,
                                        FontWeight = FontWeights.Bold };
            badge.Child = label;
            badge.Measure(new Size(Double.PositiveInfinity, Double.PositiveInfinity));
            badge.Arrange(new Rect(badge.DesiredSize));
            Place(badge, new Point(center.X, Math.Max(10, center.Y - 42)), badge.DesiredSize.Width, badge.DesiredSize.Height);
            Fade(badge, 0.95, 0, duration);
            Move(badge, Canvas.TopProperty, Math.Max(10, center.Y - 42), Math.Max(5, center.Y - 52), duration);
        }

        private void AnimateSummon(Dictionary<string, object> action, int duration)
        {
            string key = ActionKey(action);
            Point? target = CenterOf(key);
            if (!target.HasValue) return;
            string kind = action.Text("special_kind") ?? "special";
            bool special = action.Text("mode") == "special";
            string name = action.Text("name") ?? (special ? "Spezialbeschwörung" : "Normalbeschwörung");
            Color color = ActionColor(action.Text("kind"), action);
            double width = 94, height = 56;
            var ghost = MakeGhost(name, color, width, height);
            Place(ghost, target.Value, width, height);
            var scale = (ScaleTransform)ghost.RenderTransform;
            if (special)
            {
                ghost.Opacity = 0;
                Scale(scale, 0.18, 1.08, duration);
                Fade(ghost, 0, 1, duration);
                var portal = new Ellipse
                {
                    Width = 70, Height = 92, Stroke = new SolidColorBrush(color), StrokeThickness = 2,
                    Fill = new SolidColorBrush(Color.FromArgb(0x24, color.R, color.G, color.B)),
                    Opacity = 0.75, RenderTransform = new ScaleTransform(0.3, 0.3),
                    RenderTransformOrigin = new Point(0.5, 0.5)
                };
                Place(portal, target.Value, 70, 92);
                Scale((ScaleTransform)portal.RenderTransform, 0.3, 1.75, duration);
                Fade(portal, 0.75, 0, duration);
                Ring(target.Value, color, duration, 110, 90);
                Badge(target.Value, SpecialLabel(kind), color, duration);
                AnimateMaterials(action, target.Value, duration, color);
            }
            else
            {
                ghost.Opacity = 1;
                Canvas.SetTop(ghost, target.Value.Y - height / 2 + 70);
                Move(ghost, Canvas.TopProperty, target.Value.Y - height / 2 + 70,
                     target.Value.Y - height / 2, duration);
                Scale(scale, 0.72, 1.0, duration);
                Ring(target.Value, Color.FromRgb(0xF2, 0xC1, 0x4E), duration);
                Badge(target.Value, "NORMAL", Color.FromRgb(0xF2, 0xC1, 0x4E), duration);
            }
        }

        private void AnimateMaterials(Dictionary<string, object> action, Point summonPoint, int duration, Color color)
        {
            var materials = action.Get("materials") as object[];
            if (materials == null) return;
            string summonKey = ActionKey(action);
            int index = 0;
            foreach (object item in materials)
            {
                var material = Json.Object(item);
                Point start = CenterOf(MaterialKey(material)) ?? summonPoint;
                Point end = CenterOf(MaterialDestination(material, summonKey)) ?? summonPoint;
                var chip = MakeGhost(material.Text("name") ?? "Material", color, 58, 26);
                Place(chip, start, 58, 26);
                chip.Opacity = 0.9;
                int delay = index * 35;
                int chipDuration = Math.Max(300, duration - delay);
                Move(chip, Canvas.LeftProperty, start.X - 29, end.X - 29, chipDuration, delay);
                Move(chip, Canvas.TopProperty, start.Y - 13, end.Y - 13, chipDuration, delay);
                Fade(chip, 0.9, 0, chipDuration, delay);
                index++;
            }
        }

        private void AnimateSet(Dictionary<string, object> action, int duration)
        {
            Point? point = CenterOf(ActionKey(action));
            if (!point.HasValue) return;
            var ghost = MakeGhost(action.Text("name") ?? "Gesetzt", Color.FromRgb(0x9A, 0xA7, 0xBD), 84, 46);
            Place(ghost, point.Value, 84, 46);
            ghost.Opacity = 0.9;
            Scale((ScaleTransform)ghost.RenderTransform, 0.35, 1.0, duration);
            Badge(point.Value, "SETZEN", Color.FromRgb(0x9A, 0xA7, 0xBD), duration);
        }

        private void AnimateFlip(Dictionary<string, object> action, int duration)
        {
            Point? point = CenterOf(ActionKey(action));
            if (!point.HasValue) return;
            var ghost = MakeGhost(action.Text("name") ?? "Flip", Color.FromRgb(0xE8, 0xD4, 0x8A), 84, 46);
            Place(ghost, point.Value, 84, 46);
            ghost.Opacity = 1;
            var scale = (ScaleTransform)ghost.RenderTransform;
            var frames = new DoubleAnimationUsingKeyFrames();
            frames.KeyFrames.Add(new LinearDoubleKeyFrame(1.0, KeyTime.FromTimeSpan(TimeSpan.Zero)));
            frames.KeyFrames.Add(new LinearDoubleKeyFrame(0.05, KeyTime.FromTimeSpan(TimeSpan.FromMilliseconds(duration * 0.45))));
            frames.KeyFrames.Add(new LinearDoubleKeyFrame(1.0, KeyTime.FromTimeSpan(TimeSpan.FromMilliseconds(duration))));
            scale.BeginAnimation(ScaleTransform.ScaleXProperty, frames);
            Badge(point.Value, "FLIP", Color.FromRgb(0xE8, 0xD4, 0x8A), duration);
        }

        private void AnimateDestroy(Dictionary<string, object> action, int duration)
        {
            Point? point = CenterOf(ActionKey(action));
            if (!point.HasValue) return;
            var ghost = MakeGhost(action.Text("name") ?? "Zerstört", Color.FromRgb(0xFF, 0x54, 0x70), 88, 48);
            Place(ghost, point.Value, 88, 48);
            ghost.Opacity = 1;
            Scale((ScaleTransform)ghost.RenderTransform, 1.0, 1.3, duration);
            Fade(ghost, 1.0, 0, duration);
            Badge(point.Value, "ZERSTÖRT", Color.FromRgb(0xFF, 0x54, 0x70), duration);
            for (int shard = 0; shard < 6; shard++)
            {
                var piece = new Border
                {
                    Width = 5, Height = 16, Background = new SolidColorBrush(Color.FromRgb(0xFF, 0x8A, 0x99)),
                    RenderTransform = new RotateTransform(20 + shard * 28), RenderTransformOrigin = new Point(0.5, 0.5),
                    Opacity = 0.9
                };
                Place(piece, point.Value, 5, 16);
                double angle = (Math.PI * 2 * shard) / 6;
                Move(piece, Canvas.LeftProperty, point.Value.X - 2.5,
                     point.Value.X - 2.5 + Math.Cos(angle) * 48, duration);
                Move(piece, Canvas.TopProperty, point.Value.Y - 8,
                     point.Value.Y - 8 + Math.Sin(angle) * 38, duration);
                Fade(piece, 0.9, 0, duration);
            }
        }

        private void AnimateBanish(Dictionary<string, object> action, int duration)
        {
            Point? point = CenterOf(ActionKey(action));
            if (!point.HasValue) return;
            var color = Color.FromRgb(0xB9, 0x8C, 0xFF);
            var ghost = MakeGhost(action.Text("name") ?? "Verbannt", color, 88, 48);
            Place(ghost, point.Value, 88, 48);
            ghost.Opacity = 1;
            Move(ghost, Canvas.TopProperty, point.Value.Y - 24, Math.Max(4, point.Value.Y - 112), duration);
            Fade(ghost, 1.0, 0, duration);
            Ring(point.Value, color, duration, 76, 54);
            Badge(point.Value, "VERBANNT", color, duration);
        }

        private void AnimateHand(Dictionary<string, object> action, int duration)
        {
            Point? start = CenterOf(ActionKey(action));
            if (!start.HasValue) return;
            string targetKey = KeyFor(Convert.ToInt32(action["to_player"]), 0x02, 0);
            Point end = CenterOf(targetKey) ?? new Point(FxCenter().X, start.Value.Y < FxCenter().Y ? 12 : FxLayer.ActualHeight - 12);
            var color = Color.FromRgb(0x7E, 0xE0, 0xA3);
            var ghost = MakeGhost(action.Text("name") ?? "Auf die Hand", color, 82, 46);
            Place(ghost, start.Value, 82, 46);
            ghost.Opacity = 1;
            Move(ghost, Canvas.LeftProperty, start.Value.X - 41, end.X - 41, duration);
            Move(ghost, Canvas.TopProperty, start.Value.Y - 23, end.Y - 23, duration);
            Fade(ghost, 1.0, 0, duration);
            Badge(start.Value, "AUF DIE HAND", color, duration);
        }

        private void AnimateActivate(Dictionary<string, object> action, int duration)
        {
            Point? point = CenterOf(ActionKey(action));
            if (!point.HasValue) return;
            var color = Color.FromRgb(0x4E, 0xA8, 0xFF);
            Ring(point.Value, color, duration, 82, 58);
            Badge(point.Value, action.Get("chain") == null ? "AKTIVIERUNG" : "KETTE " + action["chain"], color, duration);
        }

        private int AnimateActions(object[] actions)
        {
            if (actions == null || actions.Length == 0) return 0;
            int level = AnimationLevel();
            int duration = AnimationDuration(level);
            FxLayer.Children.Clear();
            string text = null;
            var color = Colors.White;
            foreach (object item in actions)
            {
                var action = Json.Object(item);
                string kind = action.Text("kind");
                string key = ActionKey(action);
                if (level > 0 && key != null && fieldFlash.ContainsKey(key)) Flash(key, ActionColor(kind, action));
                if (level > 0)
                {
                    if (kind == "summon" || kind == "spsummon") AnimateSummon(action, duration);
                    else if (kind == "set") AnimateSet(action, duration);
                    else if (kind == "flip") AnimateFlip(action, duration);
                    else if (kind == "destroy") AnimateDestroy(action, duration);
                    else if (kind == "banish") AnimateBanish(action, duration);
                    else if (kind == "hand") AnimateHand(action, duration);
                    else if (kind == "activate") AnimateActivate(action, duration);
                }
                if (!String.IsNullOrEmpty(action.Text("text")))
                {
                    text = action.Text("text");
                    color = ActionColor(kind, action);
                }
            }
            if (text != null) ShowAction(text, color, level > 0);
            watchAnimationUntil = duration > 0 ? DateTime.UtcNow.AddMilliseconds(duration) : DateTime.MinValue;
            return duration;
        }

        private void Flash(string key, Color color)
        {
            var flash = fieldFlash[key];
            flash.BorderBrush = new SolidColorBrush(color);
            flash.Background = new SolidColorBrush(Color.FromArgb(0x55, color.R, color.G, color.B));
            var fade = new DoubleAnimation(1.0, 0.0, new Duration(TimeSpan.FromMilliseconds(1300)))
            {
                BeginTime = TimeSpan.FromMilliseconds(150)
            };
            flash.BeginAnimation(UIElement.OpacityProperty, fade);
            var cell = flash.Parent as Grid;
            var scale = cell == null ? null : cell.RenderTransform as ScaleTransform;
            if (scale != null)
            {
                var pulse = new DoubleAnimation(1.07, 1.0, new Duration(TimeSpan.FromMilliseconds(420)));
                scale.BeginAnimation(ScaleTransform.ScaleXProperty, pulse);
                scale.BeginAnimation(ScaleTransform.ScaleYProperty, pulse);
            }
        }

        private void ShowAction(string text, Color color, bool animate = true)
        {
            var label = Text("WatchAction");
            label.Text = text;
            label.Foreground = new SolidColorBrush(color);
            var bar = Find<Border>("WatchActionBar");
            bar.BorderBrush = new SolidColorBrush(color);
            bar.BeginAnimation(UIElement.OpacityProperty, null);
            bar.Opacity = 1;
            if (!animate) return;
            var appear = new DoubleAnimation(0.25, 1.0, new Duration(TimeSpan.FromMilliseconds(260)));
            bar.BeginAnimation(UIElement.OpacityProperty, appear);
        }

        private void BuildField()
        {
            var grid = Find<Grid>("WatchField");
            for (int column = 0; column < 7; column++) grid.ColumnDefinitions.Add(new ColumnDefinition());
            for (int row = 0; row < 5; row++) grid.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
            // oberer Spieler (gegenüber, um 180 Grad gedreht): seine Zone 1 liegt rechts
            FieldPile(grid, 0, 0, "Top", "Deck", "Deck");
            for (int zone = 0; zone < 5; zone++) FieldZone(grid, 0, 5 - zone, "Top", "S" + zone, SpellLabel(zone));
            FieldPile(grid, 0, 6, "Top", "Extra", "Extra Deck");
            FieldPile(grid, 1, 0, "Top", "Grave", "Friedhof");
            for (int zone = 0; zone < 5; zone++) FieldZone(grid, 1, 5 - zone, "Top", "M" + zone, "Monsterzone " + (zone + 1));
            FieldZone(grid, 1, 6, "Top", "S5", "Feldzone");
            FieldPile(grid, 2, 0, "Top", "Banished", "Verbannt");
            FieldZone(grid, 2, 2, "X", "E0", "Extra-Monsterzone");
            FieldZone(grid, 2, 4, "X", "E1", "Extra-Monsterzone");
            FieldPile(grid, 2, 6, "Bottom", "Banished", "Verbannt");
            FieldZone(grid, 3, 0, "Bottom", "S5", "Feldzone");
            for (int zone = 0; zone < 5; zone++) FieldZone(grid, 3, 1 + zone, "Bottom", "M" + zone, "Monsterzone " + (zone + 1));
            FieldPile(grid, 3, 6, "Bottom", "Grave", "Friedhof");
            FieldPile(grid, 4, 0, "Bottom", "Extra", "Extra Deck");
            for (int zone = 0; zone < 5; zone++) FieldZone(grid, 4, 1 + zone, "Bottom", "S" + zone, SpellLabel(zone));
            FieldPile(grid, 4, 6, "Bottom", "Deck", "Deck");
        }

        private static string SpellLabel(int zone)
        {
            return "Zauber/Falle " + (zone + 1) + (zone == 0 || zone == 4 ? " · Pendel" : "");
        }

        private void FieldZone(Grid grid, int row, int column, string side, string zone, string label)
        {
            bool extra = side == "X";
            var cell = new Grid { MinHeight = 56, Margin = new Thickness(2) };
            cell.Children.Add(new Border
            {
                CornerRadius = new CornerRadius(4), BorderThickness = new Thickness(1),
                BorderBrush = (Brush)window.FindResource("Line"),
                Background = new SolidColorBrush(extra ? Color.FromRgb(0x1A, 0x16, 0x2C) : Color.FromRgb(0x0E, 0x13, 0x1F))
            });
            var mark = new TextBlock
            {
                Text = label, FontSize = 10, TextWrapping = TextWrapping.Wrap, TextAlignment = TextAlignment.Center,
                Foreground = (Brush)window.FindResource("Muted"), Margin = new Thickness(4),
                HorizontalAlignment = HorizontalAlignment.Center, VerticalAlignment = VerticalAlignment.Center
            };
            cell.Children.Add(mark);
            var slot = new ContentControl { ContentTemplate = (DataTemplate)window.FindResource("WatchTile") };
            cell.Children.Add(slot);
            // Leuchtrahmen für Animationen, liegt über der Karte und fängt keine Klicks ab
            var flash = new Border
            {
                CornerRadius = new CornerRadius(4), BorderThickness = new Thickness(3), Opacity = 0,
                IsHitTestVisible = false
            };
            cell.Children.Add(flash);
            cell.RenderTransformOrigin = new Point(0.5, 0.5);
            cell.RenderTransform = new ScaleTransform(1, 1);
            fieldFlash[side + zone] = flash;
            cell.MouseLeftButtonDown += WatchPicture;
            Grid.SetRow(cell, row);
            Grid.SetColumn(cell, column);
            grid.Children.Add(cell);
            fieldSlots[side + zone] = slot;
            fieldMarks[side + zone] = mark;
        }

        private void FieldPile(Grid grid, int row, int column, string side, string kind, string label)
        {
            var button = new Button
            {
                Content = label, IsEnabled = false, Margin = new Thickness(2), MinHeight = 56, FontSize = 11,
                ToolTip = label + " öffnen"
            };
            Grid.SetRow(button, row);
            Grid.SetColumn(button, column);
            grid.Children.Add(button);
            window.RegisterName("Watch" + side + kind, button);
        }

        private void SetZone(string key, object value, bool monster, string owner)
        {
            var slot = WatchCard(value, monster);
            if (slot != null && owner != null) slot.Stats = (slot.Stats == null ? "" : slot.Stats + " · ") + owner;
            fieldSlots[key].Content = slot;
            fieldMarks[key].Visibility = slot == null ? Visibility.Visible : Visibility.Hidden;
        }

        private void SetPile(string side, string kind, string label, object[] cards)
        {
            string key = side + kind;
            var button = Button("Watch" + key);
            button.Content = cards == null ? label : label + " · " + cards.Length;
            button.IsEnabled = cards != null;
            if (cards != null) watchPiles[key] = cards;
        }

        private void ShowWatchPile(string side, string kind, string label)
        {
            object[] cards;
            if (!watchPiles.TryGetValue(side + kind, out cards)) return;
            PauseWatch(true);
            CreateWatchPile(Text("Watch" + side + "Name").Text, label, cards).ShowDialog();
        }

        private Window CreateWatchPile(string player, string label, object[] cards)
        {
            var rows = cards.Select(Json.Object).Select(data => new CardRow(data)).ToArray();
            var grid = new Grid { Margin = new Thickness(15) };
            grid.ColumnDefinitions.Add(new ColumnDefinition());
            grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(12) });
            grid.ColumnDefinitions.Add(new ColumnDefinition());
            var list = new ListBox { ItemsSource = rows, DisplayMemberPath = "Name" };
            if (cards.Length == 0)
                grid.Children.Add(new TextBlock { Text = "Dieser Stapel ist leer.", VerticalAlignment = VerticalAlignment.Center });
            else
                grid.Children.Add(list);
            var picture = new Image { Stretch = Stretch.Uniform };
            Grid.SetColumn(picture, 2);
            grid.Children.Add(picture);
            int generation = 0;
            list.SelectionChanged += async delegate
            {
                int selection = ++generation;
                var row = list.SelectedItem as CardRow;
                picture.Source = null;
                if (row == null) return;
                await Guard(async delegate
                {
                    var bitmap = await images.Load(row.Code, 0);
                    if (selection == generation) picture.Source = bitmap;
                });
            };
            var dialog = new Window
            {
                Owner = window, Title = label + " · " + player, Content = grid,
                Width = 675, Height = Math.Min(570, SystemParameters.WorkArea.Height),
                Background = window.Background, Foreground = window.Foreground,
                WindowStartupLocation = WindowStartupLocation.CenterOwner, ShowInTaskbar = false
            };
            dialog.PreviewKeyDown += delegate(object sender, KeyEventArgs args)
            {
                if (args.Key == Key.Escape) { args.Handled = true; dialog.Close(); }
            };
            if (rows.Length > 0) list.SelectedIndex = 0;
            return dialog;
        }

        private WatchSlot WatchCard(object value, bool monster)
        {
            if (value == null) return null;
            var data = Json.Object(value);
            long code = Convert.ToInt64(data["code"]);
            var slot = new WatchSlot { Name = data.Text("name") };
            var parts = new List<string>();
            int link = data.Get("link") == null ? 0 : Convert.ToInt32(data["link"]);
            if (monster && data.Get("attack") != null)
                parts.Add(link > 0 ? "Link-" + link + " · " + data["attack"] + " ATK"
                    : data["attack"] + " ATK" + (data.Get("defense") == null ? "" : " / " + data["defense"] + " DEF"));
            if (!String.IsNullOrEmpty(data.Text("pos")) && data.Text("pos") != "Angriff") parts.Add(data.Text("pos"));
            int materials = data.Get("materials") == null ? 0 : Convert.ToInt32(data["materials"]);
            if (materials > 0)
            {
                var materialNames = data.Get("material_cards") as object[];
                string suffix = materialNames == null || materialNames.Length == 0 ? "" :
                    ": " + String.Join(", ", materialNames.Take(2).Select(materialName => Convert.ToString(materialName))) +
                    (materialNames.Length > 2 ? " …" : "");
                parts.Add(materials + (materials == 1 ? " Material" : " Materialien") + suffix);
            }
            if (data.Get("counters") != null) parts.Add(data["counters"] + " Zählmarken");
            if (parts.Count > 0) slot.Stats = String.Join(" · ", parts);
            if (code == 0) return slot;
            CardRow art;
            if (!watchArt.TryGetValue(code, out art))
            {
                art = new CardRow(Json.Fields("code", code, "name", slot.Name));
                watchArt.Add(code, art);
                LoadWatchArt(art);
            }
            slot.Art = art;
            return slot;
        }

        private async void LoadWatchArt(CardRow card)
        {
            await Guard(async delegate { card.SetPicture(await images.Load(card.Code, 84)); });
        }

        private void WatchPicture(object sender, MouseButtonEventArgs args)
        {
            if (args.ClickCount != 2) return;
            var source = args.OriginalSource as FrameworkElement;
            var slot = source == null ? null : source.DataContext as WatchSlot;
            if (slot == null || slot.Art == null) return;
            PauseWatch(true);
            args.Handled = true;
            CreateCardPicture(slot.Art, images).ShowDialog();
        }

        private async Task WaitForWatchFrame(int after)
        {
            for (int attempt = 0; attempt < 65 && watchRunning && (watchSerial <= after || !watchWaiting); attempt++)
            {
                await Task.Delay(75);
                await PollWatch();
            }
            Expect(watchRunning && watchWaiting && watchSerial > after, "Das Duell hat keine weitere Aktion angezeigt.");
        }

        private async Task CaptureAnimationSeries(string directory)
        {
            var normal = Json.Fields("kind", "summon", "player", 0, "loc", 4, "seq", 0, "mode", "normal",
                "name", "Normalbeschwörung", "text", "Normalbeschwörung: Testmonster");
            var fusion = Json.Fields("kind", "spsummon", "player", 0, "loc", 4, "seq", 5, "mode", "special",
                "special_kind", "fusion", "special_label", "Fusion", "name", "Fusionsmonster",
                "text", "Spezialbeschwörung (Fusion): Fusionsmonster", "materials", new object[] {
                    Json.Fields("name", "Material A", "player", 0, "loc", 2, "seq", 0,
                        "to_player", 0, "to_loc", 16, "to_seq", 0),
                    Json.Fields("name", "Material B", "player", 0, "loc", 4, "seq", 1,
                        "to_player", 0, "to_loc", 16, "to_seq", 1)
                });
            var synchro = Json.Fields("kind", "spsummon", "player", 0, "loc", 4, "seq", 5, "mode", "special",
                "special_kind", "synchro", "special_label", "Synchro", "name", "Synchromonster",
                "text", "Spezialbeschwörung (Synchro): Synchromonster");
            var xyz = Json.Fields("kind", "spsummon", "player", 0, "loc", 4, "seq", 5, "mode", "special",
                "special_kind", "xyz", "special_label", "Xyz", "name", "Xyz-Monster",
                "text", "Spezialbeschwörung (Xyz): Xyz-Monster", "materials", new object[] {
                    Json.Fields("name", "Material A", "player", 0, "loc", 4, "seq", 0,
                        "to_player", 0, "to_loc", 128, "to_seq", 0),
                    Json.Fields("name", "Material B", "player", 0, "loc", 4, "seq", 1,
                        "to_player", 0, "to_loc", 128, "to_seq", 1)
                });
            var link = Json.Fields("kind", "spsummon", "player", 0, "loc", 4, "seq", 6, "mode", "special",
                "special_kind", "link", "special_label", "Link", "name", "Linkmonster",
                "text", "Spezialbeschwörung (Link): Linkmonster");
            var ritual = Json.Fields("kind", "spsummon", "player", 0, "loc", 4, "seq", 5, "mode", "special",
                "special_kind", "ritual", "special_label", "Ritual", "name", "Ritualmonster",
                "text", "Spezialbeschwörung (Ritual): Ritualmonster");
            var pendulum = Json.Fields("kind", "spsummon", "player", 0, "loc", 4, "seq", 5, "mode", "special",
                "special_kind", "pendulum", "special_label", "Pendel", "name", "Pendelmonster",
                "text", "Spezialbeschwörung (Pendel): Pendelmonster");
            var set = Json.Fields("kind", "set", "player", 1, "loc", 8, "seq", 3, "mode", "set",
                "name", "Gesetzte Karte", "text", "Gesetzt: Testkarte");
            var flip = Json.Fields("kind", "flip", "player", 0, "loc", 4, "seq", 2, "mode", "flip",
                "name", "Flippmonster", "text", "Flippbeschwörung: Flippmonster");
            var destroy = Json.Fields("kind", "destroy", "player", 0, "loc", 4, "seq", 2, "mode", "destroy",
                "name", "Zerstörtes Monster", "text", "Zerstört: Zerstörtes Monster");
            var banish = Json.Fields("kind", "banish", "player", 0, "loc", 4, "seq", 3, "mode", "banish",
                "name", "Verbanntes Monster", "text", "Verbannt: Verbanntes Monster");
            var hand = Json.Fields("kind", "hand", "player", 0, "loc", 4, "seq", 4, "mode", "hand",
                "name", "Handkarte", "text", "Auf die Hand: Handkarte", "to_player", 0, "to_loc", 2, "to_seq", 0);
            var activate = Json.Fields("kind", "activate", "player", 1, "loc", 8, "seq", 1, "chain", 2,
                "name", "Aktivierte Karte", "text", "Kette 2 · Aktivierte Karte");
            var cases = new object[] {
                new object[] { "normal", normal }, new object[] { "fusion", fusion },
                new object[] { "synchro", synchro }, new object[] { "xyz", xyz },
                new object[] { "link", link }, new object[] { "ritual", ritual },
                new object[] { "pendulum", pendulum }, new object[] { "set", set },
                new object[] { "flip", flip }, new object[] { "destroy", destroy },
                new object[] { "banish", banish }, new object[] { "hand", hand },
                new object[] { "activate", activate }
            };
            Combo("WatchAnimations").SelectedIndex = 0;
            foreach (object entry in cases)
            {
                var pair = (object[])entry;
                int duration = AnimateActions(new object[] { pair[1] });
                Expect(duration >= 300 && duration <= 600, "Animation außerhalb des Bereichs 300–600 ms.");
                await Task.Delay(100);
                Expect(FxLayer.Children.Count > 0, "Die Animation " + pair[0] + " hat keine Effekt-Ebene erzeugt.");
                Screenshot(System.IO.Path.Combine(directory, "animation-" + pair[0] + ".png"));
                await Task.Delay(40);
            }
            Combo("WatchAnimations").SelectedIndex = 1;
            int reduced = AnimateActions(new object[] { normal });
            Expect(reduced == 300, "Der Schalter Animationen reduziert nutzt nicht 300 ms.");
            Combo("WatchSpeed").SelectedIndex = 3;
            int fast = AnimateActions(new object[] { normal });
            Expect(fast == 300, "Sehr schnelles Tempo reduziert die Animation nicht automatisch.");
            Combo("WatchSpeed").SelectedIndex = 1;
            Combo("WatchAnimations").SelectedIndex = 2;
            int off = AnimateActions(new object[] { normal });
            Expect(off == 0 && FxLayer.Children.Count == 0, "Der Schalter Animationen aus stoppt die Effekt-Ebene nicht.");
            Combo("WatchAnimations").SelectedIndex = 0;
            FxLayer.Children.Clear();
            watchAnimationUntil = DateTime.MinValue;
        }

        private async Task TestWatcher(string directory)
        {
            ShowPage("Watch");
            await StartWatch();
            PauseWatch(true);
            await WaitForWatchFrame(0);
            int first = watchSerial;
            await Task.Delay(600);
            Expect(watchSerial == first, "Das Duell wurde trotz Pause fortgesetzt.");
            for (int step = 0; step < 7; step++)
            {
                int previous = watchSerial;
                await AdvanceWatch();
                await WaitForWatchFrame(previous);
            }
            bool liveAnimation = false;
            for (int step = 0; step < 60; step++)
            {
                if (ChainPanel.Visibility == Visibility.Visible && ChainList.Items.Count >= 2) break;
                int previous = watchSerial;
                await AdvanceWatch();
                await WaitForWatchFrame(previous);
                if (!liveAnimation && FxLayer.Children.Count > 0 && Text("WatchAction").Text.Contains("Spezialbeschwörung"))
                {
                    await Task.Delay(80);
                    Screenshot(System.IO.Path.Combine(directory, "animation-live.png"));
                    liveAnimation = true;
                }
            }
            Expect(ChainPanel.Visibility == Visibility.Visible && ChainList.Items.Count > 0,
                "Der Kettenstapel wurde im Zuschauen nicht sichtbar.");
            Expect(ChainTitle.Text.Contains("Kette"), "Der Kettenstapel hat keinen Titel.");
            var chainLinks = ChainList.Items.Cast<WatchChainLink>().ToArray();
            Expect(chainLinks.All(link => !String.IsNullOrEmpty(link.Number) && !String.IsNullOrEmpty(link.Title)),
                "Kettenglieder ohne Nummer oder Karte.");
            Screenshot(System.IO.Path.Combine(directory, "kette.png"));
            Find<CheckBox>("WatchChains").IsChecked = false;
            Expect(ChainPanel.Visibility == Visibility.Collapsed, "Der Schalter Ketten anzeigen versteckt den Stapel nicht.");
            Find<CheckBox>("WatchChains").IsChecked = true;
            Expect(ChainPanel.Visibility == Visibility.Visible, "Der Schalter Ketten anzeigen zeigt den Stapel nicht.");
            Expect(Find<ListBox>("WatchLog").Items.Count > 0 && Text("WatchBottomName").Text.Contains("LP"),
                "Beim Zuschauen fehlen Duellverlauf oder Lebenspunkte.");
            for (int attempt = 0; attempt < 20; attempt++)
            {
                bool ready = true;
                foreach (string side in new[] { "Top", "Bottom" })
                {
                    var handItems = Find<ItemsControl>("Watch" + side + "Hand").Items.Cast<WatchSlot>().ToArray();
                    if (handItems.Length > 0 && handItems.Any(item => item.Art == null)) ready = false;
                }
                if (ready) break;
                await Task.Delay(100);
            }
            int handCards = 0;
            foreach (string side in new[] { "Top", "Bottom" })
            {
                var items = Find<ItemsControl>("Watch" + side + "Hand").Items.Cast<WatchSlot>().ToArray();
                handCards += items.Length;
                Expect(items.All(item => item.Art != null),
                    "Handkarten ohne Kartenbild (" + side + ": " +
                    String.Join(", ", items.Select(item => item.Name + "/" + (item.Art == null ? "ohne Bild" : "ok"))) + ").");
                Expect(watchPiles[side + "Deck"].Length != 0 && watchPiles.ContainsKey(side + "Grave"),
                    "Deck oder Friedhof fehlt.");
            }
            Expect(handCards > 0, "Auf beiden Seiten fehlen Handkarten.");
            Expect(fieldSlots.Count == 24 && Button("WatchBottomExtra").IsEnabled && watchPiles.ContainsKey("TopBanished"),
                "Das Spielfeld (Zonen, Extra Deck, Verbannt) ist unvollständig.");
            AnimateActions(new object[] { Json.Fields("kind", "spsummon", "player", 0, "loc", 4, "seq", 5,
                "text", "Prüfung: Spezialbeschwörung") });
            Expect(fieldFlash.Count == 24 && Text("WatchAction").Text == "Prüfung: Spezialbeschwörung",
                "Die Aktionsanzeige (Animationen) funktioniert nicht.");
            await CaptureAnimationSeries(directory);
            Expect(WatchPhases.Count(name => Text("WatchPhase" + name).Style ==
                (Style)window.FindResource("WatchPhaseActive")) == 1, "Die aktive Phase ist nicht markiert.");
            var pile = CreateWatchPile("Deck A", "Deck", watchPiles["BottomDeck"]);
            Expect(((ListBox)((Grid)pile.Content).Children[0]).Items.Count == watchPiles["BottomDeck"].Length,
                "Die Karten des Stapels fehlen.");
            pile.Close();
            Screenshot(System.IO.Path.Combine(directory, "zuschauen.png"));
            await StopWatch();
            Expect(!watchRunning && Text("WatchState").Text == "Duell beendet.", "Das Duell ließ sich nicht beenden.");
        }
    }
}
