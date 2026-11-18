using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Threading;

namespace YgoKi
{
    sealed class TrainingRun
    {
        public TrainingRun(Dictionary<string, object> data) { Data = data; }
        public Dictionary<string, object> Data { get; private set; }
        public string Folder { get { return Data.Text("folder"); } }

        public override string ToString()
        {
            string state = Data.Text("state") ?? "";
            string best = Data.Get("best") == null ? "" : "  · beste Note " +
                Convert.ToDouble(Data.Get("best")).ToString("0.0", CultureInfo.GetCultureInfo("de-DE"));
            return (Data.Text("name") ?? Folder) + "  · " + state + best;
        }
    }

    sealed class QueueItem
    {
        public QueueItem(Dictionary<string, object> data) { Data = data; }
        public Dictionary<string, object> Data { get; private set; }
        public string Id { get { return Data.Text("id"); } }
        public string State { get { return Data.Text("state") ?? ""; } }

        public override string ToString()
        {
            string symbol = State == "läuft" ? "▶ " : State == "wartet" ? "○ " : State == "fertig" ? "✓ " : "! ";
            string progress = Data.Text("progress");
            return symbol + Data.Text("title") + " · " + State + (String.IsNullOrEmpty(progress) ? "" : "\n   " + progress);
        }
    }

    sealed partial class Desktop
    {
        private readonly DispatcherTimer trainTimer = new DispatcherTimer { Interval = TimeSpan.FromSeconds(2) };
        private bool trainPolling, trainVisible;
        private string trainFolder, solverLines;
        private int qwenTicks;

        private void SetupTraining()
        {
            Combo("TrainPlayers").ItemsSource = new[] { "64", "32" };
            Combo("TrainPlayers").SelectedIndex = 0;
            OnClickAsync("QwenStart", StartQwen);
            OnClickAsync("TrainStart", StartTraining);
            OnClickAsync("TrainQueue", QueueTraining);
            OnClickAsync("QueueRemove", async () =>
            {
                var item = Find<ListBox>("QueueList").SelectedItem as QueueItem;
                if (item != null) RenderQueue(Json.Object(await bridge.Call("queue_remove", Json.Fields("id", item.Id))));
            });
            OnClickAsync("QueuePause", async () =>
            {
                bool paused = (string)Button("QueuePause").Content == "Fortsetzen";
                RenderQueue(Json.Object(await bridge.Call(paused ? "queue_resume" : "queue_pause")));
            });
            OnClickAsync("QueueClear", async () => RenderQueue(Json.Object(await bridge.Call("queue_clear"))));
            OnClickAsync("ObsidianSave", async () =>
            {
                var value = Json.Object(await bridge.Call("obsidian_set", Json.Fields("vault", Field("ObsidianVault").Text.Trim())));
                Field("ObsidianVault").Text = value.Text("vault");
                Status("Obsidian-Vault gespeichert: " + value.Text("vault"));
            });
            OnClickAsync("ObsidianExport", ExportObsidian);
            OnClickAsync("ObsidianOpen", async () =>
            {
                var value = Json.Object(await bridge.Call("obsidian_settings"));
                try { Process.Start(new ProcessStartInfo("obsidian://open?path=" + Uri.EscapeDataString(value.Text("start"))) { UseShellExecute = true }); }
                catch (System.ComponentModel.Win32Exception)
                {
                    Status("Obsidian ist nicht installiert. Der Vault-Ordner wird stattdessen im Explorer geöffnet.");
                    OpenPath(value.Text("vault"));
                }
            });
            Find<ListBox>("QueueList").SelectionChanged += delegate
            {
                var item = Find<ListBox>("QueueList").SelectedItem as QueueItem;
                Button("QueueRemove").IsEnabled = item != null && item.State != "läuft";
            };
            OnClickAsync("TrainStop", () => TrainingAction("train_stop"));
            OnClickAsync("TrainResume", () => TrainingAction("train_resume"));
            OnClick("TrainReport", () => OpenPath(SelectedRunValue("report")));
            OnClick("TrainFolder", () => OpenPath(trainFolder));
            OnClickAsync("SolverStart", StartSolver);
            OnClick("SolverOpen", () => OpenPath(solverLines));
            Combo("TrainDeck").SelectionChanged += async delegate { await Guard(RefreshSolver); };
            Find<ListBox>("TrainRuns").SelectionChanged += async delegate
            {
                var run = Find<ListBox>("TrainRuns").SelectedItem as TrainingRun;
                if (run == null) return;
                trainFolder = run.Folder;
                RenderRun(run.Data);
                await Guard(PollTraining);
            };
            trainTimer.Tick += async delegate { await Guard(TrainingTick); };
            window.Closed += delegate { trainTimer.Stop(); };
        }

        private void TrainingLibrary()
        {
            var current = Combo("TrainDeck").SelectedItem as DeckRef;
            Combo("TrainDeck").ItemsSource = library;
            Combo("TrainDeck").SelectedItem = current == null ? library.FirstOrDefault() : MatchDeck(current.Name, current.Source);
        }

        private async void TrainingVisible(bool visible)
        {
            trainVisible = visible;
            if (!visible) { trainTimer.Stop(); return; }
            trainTimer.Start();
            await Guard(RefreshQwen);
            await Guard(LoadRuns);
            await Guard(RefreshQueue);
            await Guard(RefreshSolver);
            await Guard(async () =>
            {
                if (String.IsNullOrEmpty(Field("ObsidianVault").Text))
                    Field("ObsidianVault").Text = Json.Object(await bridge.Call("obsidian_settings")).Text("vault");
            });
        }

        private async Task TrainingTick()
        {
            if (!trainVisible) return;
            await PollTraining();
            await RefreshQueue();
            if (++qwenTicks % 5 == 0) await RefreshQwen();
            if (qwenTicks % 3 == 0) await RefreshSolver();
        }

        private async Task RefreshQwen()
        {
            var value = Json.Object(await bridge.Call("qwen_status"));
            bool ok = value.Get("ready") is bool && (bool)value.Get("ready");
            Text("QwenState").Text = value.Text("message");
            Text("QwenState").Foreground = (System.Windows.Media.Brush)window.FindResource(ok ? "Accent" : "Muted");
            Button("QwenStart").IsEnabled = !ok;
        }

        private async Task StartQwen()
        {
            var value = Json.Object(await bridge.Call("qwen_start"));
            Text("QwenState").Text = value.Text("message");
            Button("QwenStart").IsEnabled = false;
        }

        private async Task LoadRuns()
        {
            var runs = ((object[])await bridge.Call("train_runs")).Select(item => new TrainingRun(Json.Object(item))).ToList();
            Find<ListBox>("TrainRuns").ItemsSource = runs;
            var selected = runs.FirstOrDefault(run => run.Folder == trainFolder) ?? runs.FirstOrDefault();
            if (selected != null) Find<ListBox>("TrainRuns").SelectedItem = selected;
            else RenderRun(null);
        }

        private Dictionary<string, object> TrainingSettings()
        {
            int minDuels;
            double target;
            if (!Int32.TryParse(Field("TrainMinDuels").Text, out minDuels) || minDuels < 100 || minDuels > 100000)
                throw new InvalidOperationException("Mindestduelle: bitte eine Zahl zwischen 100 und 100000.");
            if (!Double.TryParse(Field("TrainTarget").Text.Replace(',', '.'), NumberStyles.Float, CultureInfo.InvariantCulture, out target)
                || target < 1 || target > 10)
                throw new InvalidOperationException("Zielnote: bitte eine Zahl zwischen 1 und 10.");
            return Json.Fields("players", Int32.Parse((string)Combo("TrainPlayers").SelectedItem), "min_duels", minDuels,
                "target", target, "qwen", Find<CheckBox>("TrainQwen").IsChecked == true);
        }

        private async Task QueueTraining()
        {
            var deck = Combo("TrainDeck").SelectedItem as DeckRef;
            if (deck == null) throw new InvalidOperationException("Bitte ein Deck wählen.");
            var item = Json.Fields("kind", "training", "deck", deck.Data, "settings", TrainingSettings());
            RenderQueue(Json.Object(await bridge.Call("queue_add", Json.Fields("items", new object[] { item }))));
            Status(deck.Name + " ist in der Warteschlange.");
        }

        private async Task ExportObsidian()
        {
            var value = Json.Object(await bridge.Call("obsidian_export"));
            Status("Obsidian wird im Hintergrund aktualisiert (" + value.Text("vault") + "). Fehlt bei einem Turnier noch " +
                "das Qwen-Feedback zu den Decks, dauert es ein paar Minuten.");
        }

        private async Task RefreshQueue()
        {
            RenderQueue(Json.Object(await bridge.Call("queue_overview")));
        }

        private void RenderQueue(Dictionary<string, object> overview)
        {
            var list = Find<ListBox>("QueueList");
            var selected = list.SelectedItem as QueueItem;
            var items = ((object[])overview["jobs"]).Select(job => new QueueItem(Json.Object(job))).ToList();
            list.ItemsSource = items;
            if (selected != null) list.SelectedItem = items.FirstOrDefault(item => item.Id == selected.Id);
            bool paused = overview.Get("paused") is bool && (bool)overview.Get("paused");
            bool runner = overview.Get("runner") is bool && (bool)overview.Get("runner");
            int waiting = items.Count(item => item.State == "wartet");
            Button("QueuePause").Content = paused ? "Fortsetzen" : "Anhalten";
            Text("QueueState").Text = items.Count == 0 ? "Leer. Mit „Zur Warteschlange“ laufen Trainings automatisch nacheinander." :
                (paused ? "Angehalten: der laufende Auftrag endet noch, danach startet keiner mehr. " :
                 runner ? "Läuft. " : "Bereit. ") + waiting + " wartend.";
        }

        private async Task StartTraining()
        {
            var deck = Combo("TrainDeck").SelectedItem as DeckRef;
            int minDuels;
            double target;
            if (deck == null) throw new InvalidOperationException("Bitte ein Deck wählen.");
            if (!Int32.TryParse(Field("TrainMinDuels").Text, out minDuels) || minDuels < 100 || minDuels > 100000)
                throw new InvalidOperationException("Mindestduelle: bitte eine Zahl zwischen 100 und 100000.");
            if (!Double.TryParse(Field("TrainTarget").Text.Replace(',', '.'), NumberStyles.Float, CultureInfo.InvariantCulture, out target)
                || target < 1 || target > 10)
                throw new InvalidOperationException("Zielnote: bitte eine Zahl zwischen 1 und 10.");
            bool qwen = Find<CheckBox>("TrainQwen").IsChecked == true;
            if (qwen)
            {
                var state = Json.Object(await bridge.Call("qwen_status"));
                if (!(state.Get("ready") is bool && (bool)state.Get("ready")))
                    throw new InvalidOperationException("Qwen ist noch nicht bereit. Erst „Qwen starten“ und kurz warten, oder ohne Qwen trainieren.");
            }
            var started = Json.Object(await bridge.Call("train_start", Json.Fields(
                "deck", deck.Data, "players", Int32.Parse((string)Combo("TrainPlayers").SelectedItem),
                "min_duels", minDuels, "target", target, "qwen", qwen)));
            trainFolder = started.Text("folder");
            Status("Training für " + deck.Name + " gestartet. Es läuft auch weiter, wenn du die App schließt.");
            await LoadRuns();
        }

        private async Task StartSolver()
        {
            var deck = Combo("TrainDeck").SelectedItem as DeckRef;
            int hands;
            if (deck == null) throw new InvalidOperationException("Bitte ein Deck wählen.");
            if (!Int32.TryParse(Field("SolverHands").Text, out hands) || hands < 1 || hands > 500)
                throw new InvalidOperationException("Starthände: bitte eine Zahl zwischen 1 und 500.");
            await bridge.Call("solver_start", Json.Fields("deck", deck.Data, "hands", hands));
            Status("Combo-Solver für " + deck.Name + " gestartet. Er läuft auch weiter, wenn du die App schließt.");
            await RefreshSolver();
        }

        private async Task RefreshSolver()
        {
            var deck = Combo("TrainDeck").SelectedItem as DeckRef;
            if (deck == null) return;
            var value = Json.Object(await bridge.Call("solver_status", Json.Fields("deck", deck.Data)));
            Find<TextBlock>("SolverState").Text = value.Text("message") ?? "";
            solverLines = value.Text("lines");
            Button("SolverOpen").IsEnabled = solverLines != null;
            Button("SolverStart").IsEnabled = !(value.Get("running") is bool && (bool)value.Get("running"));
        }

        private async Task TrainingAction(string method)
        {
            if (trainFolder == null) return;
            await bridge.Call(method, Json.Fields("folder", trainFolder));
            await LoadRuns();
        }

        private async Task PollTraining()
        {
            if (trainPolling || trainFolder == null) return;
            trainPolling = true;
            try { RenderRun(Json.Object(await bridge.Call("train_status", Json.Fields("folder", trainFolder)))); }
            finally { trainPolling = false; }
        }

        private string SelectedRunValue(string key)
        {
            var run = Find<ListBox>("TrainRuns").SelectedItem as TrainingRun;
            return run == null ? null : run.Data.Text(key);
        }

        private void RenderRun(Dictionary<string, object> run)
        {
            var german = CultureInfo.GetCultureInfo("de-DE");
            if (run == null)
            {
                Text("TrainHeadline").Text = "Noch kein Training";
                Text("TrainProgress").Text = "Wähle links ein Deck und starte das Training.";
                Text("TrainRatings").Text = "";
                Find<ListBox>("TrainLog").ItemsSource = null;
                foreach (string name in new[] { "TrainStop", "TrainResume", "TrainReport", "TrainFolder" }) Button(name).IsEnabled = false;
                return;
            }
            bool running = run.Get("running") is bool && (bool)run.Get("running");
            bool stopping = run.Get("stopping") is bool && (bool)run.Get("stopping");
            string state = run.Text("state") ?? "";
            Text("TrainHeadline").Text = (run.Text("deck") ?? run.Text("name")) + " · " + state + (stopping && running ? " (wird beendet)" : "");
            string progress = run.Text("message") ?? "";
            if (run.Get("valid") != null)
                progress = Convert.ToInt32(run.Get("valid")) + " von mind. " + Convert.ToInt32(run.Get("min_duels")) +
                    " gültigen Duellen · Generation " + Convert.ToInt32(run.Get("generation")) + " · " +
                    Convert.ToInt32(run.Get("players")) + " Spieler-KIs" + (run.Get("qwen") is bool && (bool)run.Get("qwen") ? " · mit Qwen" : " · ohne Qwen") +
                    "\n" + progress;
            Text("TrainProgress").Text = progress;
            var ratings = run.Get("ratings") as object[];
            Text("TrainRatings").Text = ratings == null || ratings.Length == 0 ? "Noch keine Prüfrunde." :
                "Gemessene Noten der Prüfrunden: " + String.Join(" → ", ratings.Select(r => Convert.ToDouble(r).ToString("0.0", german))) +
                " (Ziel " + Convert.ToDouble(run.Get("target") ?? 9).ToString("0.0", german) + ", zweimal in Folge)";
            var log = run.Get("log") as object[];
            Find<ListBox>("TrainLog").ItemsSource = log == null ? null : log.Cast<string>().ToList();
            Button("TrainStop").IsEnabled = running && !stopping;
            Button("TrainResume").IsEnabled = !running && (state == "unterbrochen" || state == "fehler");
            Button("TrainReport").IsEnabled = run.Text("report") != null;
            Button("TrainFolder").IsEnabled = run.Text("folder") != null;
        }

        private void OpenPath(string path)
        {
            if (String.IsNullOrEmpty(path) || !(File.Exists(path) || Directory.Exists(path))) { Status("Nicht gefunden: " + path); return; }
            Process.Start(new ProcessStartInfo(path) { UseShellExecute = true });
        }
    }
}
