using System;
using System.Collections.Generic;
using System.Collections.ObjectModel;
using System.Globalization;
using System.Linq;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Threading;

namespace YgoKi
{
    sealed class FieldEntry
    {
        public FieldEntry(DeckRef deck, double share, string trained) { Deck = deck; Share = share; Trained = trained; }
        public DeckRef Deck { get; private set; }
        public double Share { get; private set; }
        public string Trained { get; private set; }

        public override string ToString()
        {
            return Deck.Name + "  · " + Share.ToString("0.#", CultureInfo.GetCultureInfo("de-DE")) + " %  · " + Trained;
        }
    }

    sealed partial class Desktop
    {
        private static readonly string[] CutChoices = { "Automatisch", "Kein Top Cut", "Top 8", "Top 16", "Top 32", "Top 64", "Top 128", "Top 256" };
        private static readonly int[] CutValues = { -1, 0, 8, 16, 32, 64, 128, 256 };
        private readonly ObservableCollection<FieldEntry> field = new ObservableCollection<FieldEntry>();
        private readonly DispatcherTimer ycsTimer = new DispatcherTimer { Interval = TimeSpan.FromSeconds(2) };
        private bool ycsPolling, ycsVisible;
        private string ycsFolder;

        private void SetupTournament()
        {
            Combo("YcsCut").ItemsSource = CutChoices;
            Combo("YcsCut").SelectedIndex = 0;
            Find<ListBox>("YcsField").ItemsSource = field;
            Find<ListBox>("YcsField").SelectionChanged += delegate { Button("YcsRemove").IsEnabled = Find<ListBox>("YcsField").SelectedItem != null; };
            OnClickAsync("YcsAdd", AddFieldDeck);
            OnClick("YcsRemove", () =>
            {
                var entry = Find<ListBox>("YcsField").SelectedItem as FieldEntry;
                if (entry != null) field.Remove(entry);
                TournamentPlan();
            });
            Field("YcsPlayers").TextChanged += delegate { TournamentPlan(); };
            Combo("YcsCut").SelectionChanged += delegate { TournamentPlan(); };
            OnClickAsync("YcsStart", StartTournament);
            OnClickAsync("YcsQueue", QueueFieldAndTournament);
            OnClickAsync("YcsResume", ResumeTournament);
            OnClickAsync("YcsStop", async () =>
            {
                if (ycsFolder == null) return;
                await bridge.Call("train_stop", Json.Fields("folder", ycsFolder));
                await PollTournament();
            });
            OnClick("YcsReport", () => OpenPath(ycsFolder == null ? null : System.IO.Path.Combine(ycsFolder, "Bericht.html")));
            OnClick("YcsFolder", () => OpenPath(ycsFolder));
            Find<ListBox>("YcsRuns").SelectionChanged += async delegate
            {
                var run = Find<ListBox>("YcsRuns").SelectedItem as TrainingRun;
                if (run == null) return;
                ycsFolder = run.Folder;
                RenderTournament(run.Data);
                await Guard(PollTournament);
            };
            ycsTimer.Tick += async delegate { if (ycsVisible) await Guard(PollTournament); };
            window.Closed += delegate { ycsTimer.Stop(); };
            TournamentPlan();
        }

        private void TournamentLibrary()
        {
            var current = Combo("YcsDeck").SelectedItem as DeckRef;
            Combo("YcsDeck").ItemsSource = library;
            Combo("YcsDeck").SelectedItem = current == null ? library.FirstOrDefault() : MatchDeck(current.Name, current.Source);
        }

        private async void TournamentVisible(bool visible)
        {
            ycsVisible = visible;
            if (!visible) { ycsTimer.Stop(); return; }
            ycsTimer.Start();
            await Guard(LoadTournaments);
        }

        private async Task AddFieldDeck()
        {
            var deck = Combo("YcsDeck").SelectedItem as DeckRef;
            double share;
            if (deck == null) throw new InvalidOperationException("Bitte ein Deck wählen.");
            if (!Double.TryParse(Field("YcsShare").Text.Replace(',', '.'), NumberStyles.Float, CultureInfo.InvariantCulture, out share)
                || share <= 0 || share > 100)
                throw new InvalidOperationException("Anteil: bitte eine Zahl größer 0 und höchstens 100.");
            if (field.Any(entry => entry.Deck.Name == deck.Name && entry.Deck.Source == deck.Source))
                throw new InvalidOperationException(deck.Name + " ist schon im Feld.");
            string trained = "ohne Training";
            try
            {
                var value = Json.Object(await bridge.Call("deck_trained", deck.Data));
                bool released = value.Get("released") is bool && (bool)value.Get("released");
                if (value.Get("rating") != null)
                    trained = (released ? "freigegeben (" : "trainiert, nicht freigegeben (") +
                        Convert.ToDouble(value.Get("rating")).ToString("0.0", German) + ")";
            }
            catch (InvalidOperationException error) { throw new InvalidOperationException(deck.Name + ": " + error.Message); }
            field.Add(new FieldEntry(deck, share, trained));
            TournamentPlan();
        }

        private int PlannedPlayers()
        {
            int players;
            return Int32.TryParse(Field("YcsPlayers").Text, out players) ? players : 0;
        }

        private void TournamentPlan()
        {
            if (Text("YcsShareSum") == null) return;
            double sum = field.Sum(entry => entry.Share);
            Text("YcsShareSum").Text = field.Count == 0 ? "Noch keine Decks im Feld." :
                field.Count + " Decks, Summe " + sum.ToString("0.#", German) + " %" +
                (Math.Abs(sum - 100) > 0.05 ? " (wird auf 100 % umgerechnet)" : "");
            int players = PlannedPlayers();
            if (players < 4 || players > 20000) { Text("YcsPlan").Text = "Spieler: 4 bis 20000."; return; }
            int rounds = Math.Max(3, (int)Math.Ceiling(Math.Log(players, 2)));
            int cut = CutValues[Math.Max(0, Combo("YcsCut").SelectedIndex)];
            if (cut < 0)
                cut = players >= 2000 ? 128 : players >= 1000 ? 64 : players >= 400 ? 32 : players >= 100 ? 16 : players >= 32 ? 8 : players >= 8 ? 4 : 0;
            long duels = (long)Math.Round(rounds * (players / 2) * 2.4 + Math.Max(cut - 1, 0) * 2.4);
            Text("YcsPlan").Text = rounds + " Schweizer Runden, " + (cut > 0 ? "Top " + cut : "kein Top Cut") +
                ", rund " + duels.ToString("N0", German) + " Duelle.";
        }

        private async Task QueueFieldAndTournament()
        {
            int players = PlannedPlayers();
            if (field.Count < 2) throw new InvalidOperationException("Bitte mindestens zwei Decks ins Feld aufnehmen.");
            if (players < 4 || players > 20000) throw new InvalidOperationException("Spieler: bitte 4 bis 20000.");
            bool qwen = Find<CheckBox>("YcsQwen").IsChecked == true;
            var items = new List<object>();
            foreach (var entry in field.Where(entry => !entry.Trained.StartsWith("freigegeben")))
                items.Add(Json.Fields("kind", "training", "deck", entry.Deck.Data, "settings",
                    Json.Fields("players", 64, "min_duels", 1000, "target", 9.0, "qwen", qwen)));
            var entries = field.Select(entry => (object)Json.Fields("name", entry.Deck.Name, "source", entry.Deck.Source, "share", entry.Share)).ToArray();
            items.Add(Json.Fields("kind", "turnier", "field", entries, "settings", Json.Fields("players", players,
                "top_cut", CutValues[Math.Max(0, Combo("YcsCut").SelectedIndex)], "qwen", qwen)));
            await bridge.Call("queue_add", Json.Fields("items", items.ToArray()));
            Status((items.Count - 1) + " Trainings und das Turnier stehen in der Warteschlange (Reiter KI-Training).");
        }

        private async Task StartTournament()
        {
            int players = PlannedPlayers();
            if (field.Count < 2) throw new InvalidOperationException("Bitte mindestens zwei Decks ins Feld aufnehmen.");
            if (players < 4 || players > 20000) throw new InvalidOperationException("Spieler: bitte 4 bis 20000.");
            bool qwen = Find<CheckBox>("YcsQwen").IsChecked == true;
            if (qwen)
            {
                var state = Json.Object(await bridge.Call("qwen_status"));
                if (!(state.Get("ready") is bool && (bool)state.Get("ready")))
                    throw new InvalidOperationException("Der KI-Coach ist nicht bereit: " + state.Text("message") +
                        " Im Reiter KI-Training prüfen oder den Haken entfernen.");
            }
            var entries = field.Select(entry => (object)Json.Fields("name", entry.Deck.Name, "source", entry.Deck.Source, "share", entry.Share)).ToArray();
            var started = Json.Object(await bridge.Call("ycs_start", Json.Fields("field", entries, "players", players,
                "top_cut", CutValues[Math.Max(0, Combo("YcsCut").SelectedIndex)], "qwen", qwen)));
            ycsFolder = started.Text("folder");
            Status("Turnier mit " + players + " KI-Spielern gestartet. Es läuft auch weiter, wenn du die App schließt.");
            await LoadTournaments();
        }

        private async Task ResumeTournament()
        {
            if (ycsFolder == null) return;
            var started = Json.Object(await bridge.Call("turnier_resume", Json.Fields("folder", ycsFolder)));
            if (started.Text("folder") != null) ycsFolder = started.Text("folder");
            Status("Turnier wird ab dem letzten Zwischenstand fortgesetzt.");
            await LoadTournaments();
        }

        private async Task LoadTournaments()
        {
            var runs = ((object[])await bridge.Call("ycs_runs")).Select(item => new TrainingRun(Json.Object(item))).ToList();
            Find<ListBox>("YcsRuns").ItemsSource = runs;
            var selected = runs.FirstOrDefault(run => run.Folder == ycsFolder) ?? runs.FirstOrDefault();
            if (selected != null) Find<ListBox>("YcsRuns").SelectedItem = selected;
            else RenderTournament(null);
        }

        private async Task PollTournament()
        {
            if (ycsPolling || ycsFolder == null) return;
            ycsPolling = true;
            try { RenderTournament(Json.Object(await bridge.Call("train_status", Json.Fields("folder", ycsFolder)))); }
            finally { ycsPolling = false; }
        }

        private void RenderTournament(Dictionary<string, object> run)
        {
            if (run == null)
            {
                Text("YcsHeadline").Text = "Noch kein Turnier";
                Text("YcsProgress").Text = "Stell links das Meta-Feld zusammen und starte das Turnier.";
                Find<ListBox>("YcsLog").ItemsSource = null;
                foreach (string name in new[] { "YcsResume", "YcsStop", "YcsReport", "YcsFolder" }) Button(name).IsEnabled = false;
                return;
            }
            bool running = run.Get("running") is bool && (bool)run.Get("running");
            bool stopping = run.Get("stopping") is bool && (bool)run.Get("stopping");
            Text("YcsHeadline").Text = (run.Text("deck") ?? run.Text("name")) + " · " + (run.Text("state") ?? "") +
                (stopping && running ? " (wird beendet)" : "");
            string progress = run.Text("message") ?? "";
            if (run.Get("rounds") != null)
                progress = "Runde " + Convert.ToInt32(run.Get("round")) + " von " + Convert.ToInt32(run.Get("rounds")) +
                    " · " + Convert.ToInt64(run.Get("matches")).ToString("N0", German) + " Matches · " +
                    Convert.ToInt64(run.Get("duels")).ToString("N0", German) + " Duelle\n" + progress;
            Text("YcsProgress").Text = progress;
            var log = run.Get("log") as object[];
            Find<ListBox>("YcsLog").ItemsSource = log == null ? null : log.Cast<string>().ToList();
            Button("YcsResume").IsEnabled = !running && (run.Text("state") ?? "") == "unterbrochen";
            Button("YcsStop").IsEnabled = running && !stopping;
            Button("YcsReport").IsEnabled = run.Text("report") != null;
            Button("YcsFolder").IsEnabled = run.Text("folder") != null;
        }
    }
}
