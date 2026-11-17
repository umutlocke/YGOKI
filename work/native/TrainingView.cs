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

    sealed partial class Desktop
    {
        private readonly DispatcherTimer trainTimer = new DispatcherTimer { Interval = TimeSpan.FromSeconds(2) };
        private bool trainPolling, trainVisible;
        private string trainFolder;
        private int qwenTicks;

        private void SetupTraining()
        {
            Combo("TrainPlayers").ItemsSource = new[] { "64", "32" };
            Combo("TrainPlayers").SelectedIndex = 0;
            OnClickAsync("QwenStart", StartQwen);
            OnClickAsync("TrainStart", StartTraining);
            OnClickAsync("TrainStop", () => TrainingAction("train_stop"));
            OnClickAsync("TrainResume", () => TrainingAction("train_resume"));
            OnClick("TrainReport", () => OpenPath(SelectedRunValue("report")));
            OnClick("TrainFolder", () => OpenPath(trainFolder));
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
        }

        private async Task TrainingTick()
        {
            if (!trainVisible) return;
            await PollTraining();
            if (++qwenTicks % 5 == 0) await RefreshQwen();
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
