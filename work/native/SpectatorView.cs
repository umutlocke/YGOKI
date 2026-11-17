using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
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
        private bool watchRunning, watchPaused, watchPolling, watchWaiting;
        private int watchSerial, watchGeneration;
        private DateTime watchNextAfter;
        private static readonly int[] WatchDelays = { 900, 420, 210, 85 };

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
            foreach (string name in new[] { "WatchTopMonsters", "WatchTopSpells", "WatchBottomMonsters", "WatchBottomSpells" })
                Find<ItemsControl>(name).MouseLeftButtonDown += WatchPicture;
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
            foreach (string side in new[] { "Top", "Bottom" })
            {
                Find<ItemsControl>("Watch" + side + "Monsters").ItemsSource = new WatchSlot[7];
                Find<ItemsControl>("Watch" + side + "Spells").ItemsSource = new WatchSlot[8];
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
            Text("WatchState").Text = "Zug " + frame["turn"] + " · " + frame.Text("phase")
                + (active >= 0 && active < players.Length ? " · " + players[active].Text("name") : "");
            for (int side = 0; side < players.Length; side++)
            {
                string panel = side == 0 ? "Bottom" : "Top";
                var player = players[side];
                Text("Watch" + panel + "Name").Text = player.Text("name") + " · " + player["lp"] + " LP";
                Text("Watch" + panel + "Info").Text = "Hand " + player["hand"] + "  ·  Deck " + player["deck"] +
                    "  ·  Friedhof " + player["grave"] + "  ·  " + player.Text("strategy");
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
            Screenshot(System.IO.Path.Combine(directory, "zuschauen.png"));
            await StopWatch();
            Expect(!watchRunning && Text("WatchState").Text == "Duell beendet.", "Das Duell ließ sich nicht beenden.");
        }
    }
}
