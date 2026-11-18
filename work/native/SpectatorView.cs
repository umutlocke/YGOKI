using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
using System.Windows.Media.Animation;
using System.Windows.Threading;

namespace YgoKi
{
    sealed class WatchSlot
    {
        public string Name { get; set; }
        public string Stats { get; set; }
        public CardRow Art { get; set; }
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
        private int watchSerial, watchGeneration;
        private DateTime watchNextAfter;
        private static readonly int[] WatchDelays = { 900, 420, 210, 85 };
        private static readonly string[] WatchPhases = { "Draw", "Standby", "Main1", "Battle", "Main2", "End" };
        private static readonly int[] WatchPhaseMasks = { 1, 2, 4, 248, 256, 512 };

        private void SetupWatcher()
        {
            Combo("WatchFormat").ItemsSource = new[] { "Vorschau", "TCG", "OCG" };
            Combo("WatchFormat").SelectedIndex = 0;
            Combo("WatchSpeed").ItemsSource = new[] { "Langsam", "Normal", "Schnell", "Sehr schnell" };
            Combo("WatchSpeed").SelectedIndex = 1;
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
            Button("WatchNext").IsEnabled = watchRunning && watchPaused && watchWaiting;
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
            if (!watchWaiting || watchPolling) return;
            watchPolling = true;
            watchWaiting = false;
            WatchButtons();
            try { await bridge.Call("watch_next", Json.Fields("serial", watchSerial)); }
            finally { watchPolling = false; }
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
                    RenderWatch(frame);
                    watchNextAfter = DateTime.UtcNow.AddMilliseconds(WatchDelays[Math.Max(0, Combo("WatchSpeed").SelectedIndex)]);
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

        private void RenderWatch(Dictionary<string, object> frame)
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
            AnimateActions(frame.Array("actions"));
            var log = Find<ListBox>("WatchLog");
            foreach (object entry in frame.Array("events"))
            {
                if (log.Items.Count == 360) log.Items.RemoveAt(0);
                log.Items.Add(entry);
            }
            if (log.Items.Count > 0) log.ScrollIntoView(log.Items[log.Items.Count - 1]);
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

        private static Color ActionColor(string kind)
        {
            switch (kind)
            {
                case "summon": return Color.FromRgb(0xF2, 0xC1, 0x4E);    // Normalbeschwörung: gold
                case "spsummon": return Color.FromRgb(0xFF, 0x8A, 0x3D);  // Spezialbeschwörung: orange
                case "flip": return Color.FromRgb(0xE8, 0xD4, 0x8A);
                case "activate": return Color.FromRgb(0x4E, 0xA8, 0xFF);  // Aktivierung/Kette: blau
                case "set": return Color.FromRgb(0x9A, 0xA7, 0xBD);       // Setzen: grau
                case "attack": return Color.FromRgb(0xFF, 0x54, 0x70);    // Angriff: rot
                case "target": return Color.FromRgb(0xFF, 0xB3, 0xC0);
                case "destroy": return Color.FromRgb(0xB0, 0x30, 0x40);   // Zerstört: dunkelrot
                default: return Color.FromRgb(0xAB, 0xB6, 0xCC);
            }
        }

        private string ActionKey(Dictionary<string, object> action)
        {
            if (action.Get("player") == null || action.Get("loc") == null || action.Get("seq") == null) return null;
            int player = Convert.ToInt32(action["player"]);
            int location = Convert.ToInt32(action["loc"]);
            int sequence = Convert.ToInt32(action["seq"]);
            string side = player == 0 ? "Bottom" : "Top";
            if (location == 4)
            {
                if (sequence >= 5) return "XE" + (player == 0 ? sequence - 5 : 1 - (sequence - 5));
                return side + "M" + sequence;
            }
            if (location == 8 && sequence <= 5) return side + "S" + sequence;
            return null;
        }

        private void AnimateActions(object[] actions)
        {
            if (actions == null || actions.Length == 0) return;
            string text = null;
            var color = Colors.White;
            foreach (object item in actions)
            {
                var action = Json.Object(item);
                string kind = action.Text("kind");
                string key = ActionKey(action);
                if (key != null && fieldFlash.ContainsKey(key)) Flash(key, ActionColor(kind));
                if (!String.IsNullOrEmpty(action.Text("text")))
                {
                    text = action.Text("text");
                    color = ActionColor(kind);
                }
            }
            if (text != null) ShowAction(text, color);
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

        private void ShowAction(string text, Color color)
        {
            var label = Text("WatchAction");
            label.Text = text;
            label.Foreground = new SolidColorBrush(color);
            var bar = Find<Border>("WatchActionBar");
            bar.BorderBrush = new SolidColorBrush(color);
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
            if (materials > 0) parts.Add(materials + (materials == 1 ? " Material" : " Materialien"));
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
            Expect(Find<ListBox>("WatchLog").Items.Count > 0 && Text("WatchBottomName").Text.Contains("LP"),
                "Beim Zuschauen fehlen Duellverlauf oder Lebenspunkte.");
            foreach (string side in new[] { "Top", "Bottom" })
            {
                var items = Find<ItemsControl>("Watch" + side + "Hand").Items.Cast<WatchSlot>().ToArray();
                Expect(items.Length != 0 && items.All(item => item.Art != null), "Die Handkarten fehlen.");
                Expect(watchPiles[side + "Deck"].Length != 0 && watchPiles.ContainsKey(side + "Grave"),
                    "Deck oder Friedhof fehlt.");
            }
            Expect(fieldSlots.Count == 24 && Button("WatchBottomExtra").IsEnabled && watchPiles.ContainsKey("TopBanished"),
                "Das Spielfeld (Zonen, Extra Deck, Verbannt) ist unvollständig.");
            AnimateActions(new object[] { Json.Fields("kind", "spsummon", "player", 0, "loc", 4, "seq", 5,
                "text", "Prüfung: Spezialbeschwörung") });
            Expect(fieldFlash.Count == 24 && Text("WatchAction").Text == "Prüfung: Spezialbeschwörung",
                "Die Aktionsanzeige (Animationen) funktioniert nicht.");
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
