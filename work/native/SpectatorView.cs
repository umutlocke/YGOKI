using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Media;
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
            foreach (string side in new[] { "Top", "Bottom" })
            {
                foreach (string group in new[] { "Monsters", "Spells", "Hand" })
                    Find<ItemsControl>("Watch" + side + group).MouseLeftButtonDown += WatchPicture;
                OnClick("Watch" + side + "Deck", () => ShowWatchPile(side, "Deck", "Deck"));
                OnClick("Watch" + side + "Grave", () => ShowWatchPile(side, "Grave", "Friedhof"));
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
            foreach (string side in new[] { "Top", "Bottom" })
            {
                SetPile(side, "Deck", "Deck", null);
                SetPile(side, "Grave", "Friedhof", null);
                Find<ItemsControl>("Watch" + side + "Monsters").ItemsSource = new WatchSlot[7];
                Find<ItemsControl>("Watch" + side + "Spells").ItemsSource = new WatchSlot[8];
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
                SetPile(panel, "Grave", "Friedhof", player.Array("grave_cards"));
                Find<ItemsControl>("Watch" + panel + "Monsters").ItemsSource = player.Array("monsters").Select(value => WatchCard(value, true)).ToArray();
                Find<ItemsControl>("Watch" + panel + "Spells").ItemsSource = player.Array("spells").Select(value => WatchCard(value, false)).ToArray();
            }
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
            if (monster && data.Get("attack") != null)
                slot.Stats = data["attack"] + " ATK" + (data.Get("defense") == null ? "" : " / " + data["defense"] + " DEF");
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
