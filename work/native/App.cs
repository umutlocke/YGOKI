using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Markup;
using System.Windows.Media;
using System.Windows.Media.Imaging;
using System.Windows.Threading;
using Microsoft.Win32;

namespace YgoKi
{
    static class Json
    {
        public static Dictionary<string, object> Fields(params object[] pairs)
        {
            var result = new Dictionary<string, object>();
            for (int i = 0; i < pairs.Length; i += 2) result.Add((string)pairs[i], pairs[i + 1]);
            return result;
        }

        public static Dictionary<string, object> Object(object value)
        {
            return (Dictionary<string, object>)value;
        }

        public static object Get(this Dictionary<string, object> value, string key)
        {
            object result;
            return value.TryGetValue(key, out result) ? result : null;
        }

        public static string Text(this Dictionary<string, object> value, string key)
        {
            return value.Get(key) as string;
        }

        public static object[] Array(this Dictionary<string, object> value, string key)
        {
            return (object[])value[key];
        }
    }

    sealed class Bridge : IDisposable
    {
        private readonly Process process;
        private readonly StreamWriter input;
        private readonly SemaphoreSlim queue = new SemaphoreSlim(1);
        private readonly JavaScriptSerializer serializer = new JavaScriptSerializer { MaxJsonLength = 64 * 1024 * 1024 };
        private volatile string error;

        public Bridge(string root, string testData)
        {
            string work = Path.Combine(root, "work");
            string backend = Path.Combine(work, "native_bridge.py");
            var encoding = new UTF8Encoding(false);
            var start = new ProcessStartInfo(Path.Combine(work, "upstream", "python-win32", "python.exe"))
            {
                Arguments = "-X utf8 \"" + backend + "\"" +
                    (testData == null ? "" : " --test-data \"" + testData + "\""),
                WorkingDirectory = root,
                UseShellExecute = false,
                CreateNoWindow = true,
                RedirectStandardInput = true,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                StandardOutputEncoding = encoding,
                StandardErrorEncoding = encoding
            };
            start.EnvironmentVariables["XDG_CACHE_HOME"] = Path.Combine(work, "cache");
            process = Process.Start(start);
            input = new StreamWriter(process.StandardInput.BaseStream, encoding) { AutoFlush = true };
            process.ErrorDataReceived += delegate(object sender, DataReceivedEventArgs e)
            {
                if (!String.IsNullOrWhiteSpace(e.Data)) error = e.Data;
            };
            process.BeginErrorReadLine();
        }

        public async Task<object> Call(string method, Dictionary<string, object> fields = null)
        {
            await queue.WaitAsync().ConfigureAwait(false);
            try
            {
                if (process.HasExited) throw new IOException(error ?? "Der lokale Hintergrundprozess wurde beendet.");
                await input.WriteLineAsync(serializer.Serialize(Json.Fields(
                    "method", method, "data", fields ?? Json.Fields()))).ConfigureAwait(false);
                string line = await process.StandardOutput.ReadLineAsync().ConfigureAwait(false);
                if (line == null) throw new IOException(error ?? "Der lokale Hintergrundprozess hat nicht geantwortet.");
                var envelope = Json.Object(serializer.DeserializeObject(line));
                if (envelope.ContainsKey("error")) throw new InvalidOperationException(envelope.Text("error"));
                return envelope["result"];
            }
            finally { queue.Release(); }
        }

        public void Dispose()
        {
            try
            {
                input.Dispose();
                if (!process.WaitForExit(1600)) process.Kill();
            }
            catch (InvalidOperationException) { }
            catch (IOException) { }
            finally { process.Dispose(); }
        }
    }

    sealed class DeckRef
    {
        public DeckRef(Dictionary<string, object> value) { Name = value.Text("name"); Source = value.Text("source"); }
        public string Name { get; private set; }
        public string Source { get; private set; }
        public Dictionary<string, object> Data { get { return Json.Fields("name", Name, "source", Source); } }
        public override string ToString() { return Name + (Source == "saved" ? "  · gespeichert" : "  · Vorlage"); }
    }

    sealed class CardRow
    {
        public CardRow(Dictionary<string, object> data)
        {
            Code = Convert.ToInt64(data["code"]);
            Name = data.Text("name");
            Type = data.Text("type");
            Zone = data.Text("zone");
            int limit = data.ContainsKey("limit") ? Convert.ToInt32(data["limit"]) : 3;
            Availability = data.Text("pool_issue") ??
                (limit == 0 ? "Verboten" : limit < 3 ? "Max. " + limit : data.Text("scope"));
            if (Object.Equals(data.Get("script"), false)) Availability += " · Skript fehlt";
        }
        public long Code { get; private set; }
        public string Name { get; private set; }
        public string Type { get; private set; }
        public string Zone { get; private set; }
        public string Availability { get; private set; }
        public int Quantity { get; set; }
        public bool Locked { get; set; }
        public string LockLabel { get { return Locked ? "Gesperrt" : ""; } }
    }

    sealed class Desktop
    {
        private static readonly string[] Zones = { "main", "extra", "side" };
        private static readonly string[] ZoneButtons = { "MainZone", "ExtraZone", "SideZone" };
        private static readonly string[] ZoneLabels = { "Main Deck", "Extra Deck", "Side Deck" };
        private static readonly CultureInfo German = CultureInfo.GetCultureInfo("de-DE");
        private readonly Window window;
        private readonly Bridge bridge;
        private readonly DispatcherTimer catalogTimer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(150) };
        private readonly DispatcherTimer checkTimer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(120) };
        private readonly DispatcherTimer jobTimer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(450) };
        private readonly Dictionary<string, List<long>> sections = Zones.ToDictionary(zone => zone, zone => new List<long>());
        private readonly Dictionary<long, CardRow> cards = new Dictionary<long, CardRow>();
        private readonly HashSet<long> locks = new HashSet<long>();
        private List<DeckRef> library = new List<DeckRef>();
        private string zone = "main";
        private string openedName, openedSource, revision, jobId;
        private bool updateControls, ready, dirty, loadingDeck, jobBusy, polling;
        private int offset, total, deckVersion, searchVersion;
        private object lastResult;

        public Desktop(Window window, Bridge bridge, string testData)
        {
            this.window = window;
            this.bridge = bridge;
            Setup();
            window.Loaded += async delegate
            {
                try
                {
                    await Initialize();
                    if (testData != null)
                    {
                        await SelfTest(testData);
                        Application.Current.Shutdown(0);
                    }
                }
                catch (Exception error)
                {
                    if (testData != null)
                    {
                        File.WriteAllText(Path.Combine(testData, "error.txt"), error.ToString());
                        Application.Current.Shutdown(1);
                    }
                    else Status("Start fehlgeschlagen. " + error.Message);
                }
            };
            window.Closing += delegate(object sender, System.ComponentModel.CancelEventArgs e)
            {
                if (testData == null && !CanLeaveDeck()) e.Cancel = true;
            };
            window.Closed += delegate { catalogTimer.Stop(); checkTimer.Stop(); jobTimer.Stop(); };
        }

        private T Find<T>(string name) where T : class { return (T)window.FindName(name); }
        private Button Button(string name) { return Find<Button>(name); }
        private TextBox Field(string name) { return Find<TextBox>(name); }
        private ComboBox Combo(string name) { return Find<ComboBox>(name); }
        private ListView Table(string name) { return Find<ListView>(name); }
        private TextBlock Text(string name) { return Find<TextBlock>(name); }
        private string Choice(string name) { return Combo(name).SelectedItem as string; }
        private string Banlist(string name) { return Choice(name) == "Standard" ? null : Choice(name); }
        private void Status(string text) { Text("Status").Text = text; }

        private async Task Guard(Func<Task> action)
        {
            try { await action(); }
            catch (Exception error) { Status(error.Message); }
        }

        private void OnClick(string name, Action handler)
        {
            Button(name).Click += delegate { handler(); };
        }

        private void OnClickAsync(string name, Func<Task> handler)
        {
            Button(name).Click += async delegate { await Guard(handler); };
        }

        private void ConfigureCombo(string name, string[] items, int selected = 0)
        {
            Combo(name).ItemsSource = items;
            Combo(name).SelectedIndex = selected;
        }

        private void Setup()
        {
            ConfigureCombo("EditorFormat", new[] { "TCG", "OCG", "Vorschau" });
            ConfigureCombo("CompareFormat", new[] { "TCG", "OCG", "Vorschau" });
            ConfigureCombo("EditorBanlist", new[] { "Standard", "TCG", "OCG", "Keine" });
            ConfigureCombo("CompareBanlist", new[] { "Standard", "TCG", "OCG", "Keine" });
            ConfigureCombo("CardKind", new[] { "Alle Typen", "Monster", "Extra Deck", "Zauber", "Fallen" });
            ConfigureCombo("AddTarget", new[] { "Passender Bereich", "Side Deck" });
            OnClick("ShowEditor", () => ShowPage(false));
            OnClick("ShowComparison", () => ShowPage(true));
            OnClick("NewDeck", NewDeck);
            OnClickAsync("ImportDeck", ImportFile);
            OnClickAsync("ExportYdk", () => ExportDeck("ydk"));
            OnClickAsync("ExportTxt", () => ExportDeck("txt"));
            OnClickAsync("SaveDeck", SaveDeck);
            for (int i = 0; i < Zones.Length; i++)
            {
                string selected = Zones[i];
                OnClick(ZoneButtons[i], () => { zone = selected; RenderDeck(null); });
            }
            OnClick("DeckMinus", () => ChangeQuantity(-1));
            OnClick("DeckPlus", () => ChangeQuantity(1));
            OnClick("ToggleLock", ToggleLock);
            OnClick("MoveCard", MoveCard);
            OnClick("AddCard", AddCard);
            OnClick("PrevCards", () => { offset = Math.Max(0, offset - 24); ScheduleSearch(false); });
            OnClick("NextCards", () => { if (offset + 24 < total) offset += 24; ScheduleSearch(false); });
            Table("Catalogue").MouseDoubleClick += delegate { AddCard(); };
            Table("Catalogue").SelectionChanged += delegate { Button("AddCard").IsEnabled = Table("Catalogue").SelectedItem != null; };
            Table("DeckCards").SelectionChanged += delegate { UpdateCardControls(); };
            Combo("Library").SelectionChanged += async delegate
            {
                if (updateControls || !ready) return;
                var selected = Combo("Library").SelectedItem as DeckRef;
                if (selected == null || loadingDeck || !CanLeaveDeck()) { SelectLibrary(); return; }
                loadingDeck = true;
                try { await Guard(() => OpenDeck(selected)); }
                finally { loadingDeck = false; SelectLibrary(); }
            };
            Field("DeckName").TextChanged += delegate { if (ready && !updateControls) Changed(); };
            Field("CardQuery").TextChanged += delegate { ScheduleSearch(true); };
            Combo("CardKind").SelectionChanged += delegate { ScheduleSearch(true); };
            Combo("EditorFormat").SelectionChanged += delegate { ScheduleSearch(true); ScheduleCheck(); };
            Combo("EditorBanlist").SelectionChanged += delegate { ScheduleSearch(true); ScheduleCheck(); };
            checkTimer.Tick += async delegate { checkTimer.Stop(); await Guard(CheckDeck); };
            catalogTimer.Tick += async delegate { catalogTimer.Stop(); await Guard(SearchCards); };
            jobTimer.Tick += async delegate { await Guard(PollComparison); };
            Find<ListBox>("Opponents").SelectionChanged += delegate { PlannedGames(); };
            Field("Blocks").TextChanged += delegate { PlannedGames(); };
            OnClickAsync("StartComparison", StartComparison);
            OnClickAsync("CancelComparison", CancelComparison);
            OnClickAsync("ExportReport", () => ExportReport("bericht", "Markdown|*.md"));
            OnClickAsync("ExportGames", () => ExportReport("einzelspiele", "JSON Lines|*.jsonl"));
        }

        private async Task Initialize()
        {
            Status("Lade Kartendaten und Decks…");
            await LoadLibrary();
            var selected = library.FirstOrDefault(item => item.Name == "HERO" && item.Source == "original")
                           ?? library.FirstOrDefault();
            ready = true;
            if (selected != null) await OpenDeck(selected);
            else NewDeck();
            await SearchCards();
            await CheckDeck();
        }

        private async Task LoadLibrary()
        {
            var refresh = ((object[])await bridge.Call("decks")).Select(item => new DeckRef(Json.Object(item))).ToList();
            var original = Combo("OriginalDeck").SelectedItem as DeckRef;
            var variant = Combo("VariantDeck").SelectedItem as DeckRef;
            var opponents = Find<ListBox>("Opponents").SelectedItems.Cast<DeckRef>().ToList();
            library = refresh;
            updateControls = true;
            Combo("Library").ItemsSource = library;
            Combo("OriginalDeck").ItemsSource = library;
            Combo("VariantDeck").ItemsSource = library;
            Find<ListBox>("Opponents").ItemsSource = library;
            if (original != null) Combo("OriginalDeck").SelectedItem = MatchDeck(original.Name, original.Source);
            if (variant != null) Combo("VariantDeck").SelectedItem = MatchDeck(variant.Name, variant.Source);
            foreach (var item in opponents)
            {
                var match = MatchDeck(item.Name, item.Source);
                if (match != null) Find<ListBox>("Opponents").SelectedItems.Add(match);
            }
            updateControls = false;
            SelectLibrary();
        }

        private DeckRef MatchDeck(string name, string source)
        {
            return library.FirstOrDefault(item => item.Source == source &&
                String.Equals(item.Name, name, StringComparison.OrdinalIgnoreCase));
        }

        private void SelectLibrary()
        {
            updateControls = true;
            Combo("Library").SelectedItem = MatchDeck(openedName, openedSource);
            updateControls = false;
        }

        private bool CanLeaveDeck()
        {
            return !dirty || MessageBox.Show(window, "Ungespeicherte Änderungen verwerfen?", "Deck wechseln",
                MessageBoxButton.YesNo, MessageBoxImage.Question) == MessageBoxResult.Yes;
        }

        private async Task OpenDeck(DeckRef selection)
        {
            ApplyDeck(Json.Object(await bridge.Call("open", selection.Data)), false);
        }

        private void ApplyDeck(Dictionary<string, object> data, bool markDirty)
        {
            openedName = data.Text("name");
            openedSource = data.Text("source");
            revision = data.Text("revision");
            var loaded = Json.Object(data["sections"]);
            cards.Clear();
            foreach (var card in Json.Object(data["cards"]).Values)
            {
                var row = new CardRow(Json.Object(card));
                cards[row.Code] = row;
            }
            foreach (var name in Zones) sections[name] = loaded.Array(name).Select(Convert.ToInt64).ToList();
            locks.Clear();
            locks.UnionWith(data.Array("locked").Select(Convert.ToInt64));
            dirty = markDirty;
            zone = "main";
            updateControls = true;
            Field("DeckName").Text = openedName;
            updateControls = false;
            SelectLibrary();
            RenderDeck(null);
            ScheduleCheck();
            Status(markDirty ? "Importierte Arbeitskopie" : openedSource == "saved" ? "Lokal gespeichert" : "Importierte Vorlage");
        }

        private void NewDeck()
        {
            if (!ready || loadingDeck || !CanLeaveDeck()) return;
            ApplyDeck(Json.Fields("name", "Neues Deck", "sections", Zones.ToDictionary(name => name, name => (object)new object[0]),
                "cards", Json.Fields(), "locked", new object[0]), false);
            Status("Neue Arbeitskopie");
            Field("DeckName").SelectAll();
            Field("DeckName").Focus();
        }

        private async Task ImportFile()
        {
            if (!ready || loadingDeck || !CanLeaveDeck()) return;
            var dialog = new OpenFileDialog { Filter = "Yu-Gi-Oh!-Decks (*.ydk)|*.ydk", CheckFileExists = true };
            if (dialog.ShowDialog(window) != true) return;
            loadingDeck = true;
            try
            {
                if (new FileInfo(dialog.FileName).Length > 160 * 1024) throw new IOException("Diese Deckdatei ist zu groß.");
                await ImportDeck(Path.GetFileNameWithoutExtension(dialog.FileName), File.ReadAllText(dialog.FileName, new UTF8Encoding(false, true)));
            }
            finally { loadingDeck = false; }
        }

        private async Task ImportDeck(string name, string content)
        {
            ApplyDeck(Json.Object(await bridge.Call("import", Json.Fields("name", name, "text", content))), true);
        }

        private Dictionary<string, object> Draft()
        {
            return Json.Fields("name", Field("DeckName").Text.Trim(), "sections",
                sections.ToDictionary(section => section.Key, section => section.Value.ToArray()),
                "locked", locks.OrderBy(code => code).ToArray());
        }

        private async Task SaveDeck()
        {
            if (!ready || loadingDeck) return;
            loadingDeck = true;
            Button("SaveDeck").IsEnabled = false;
            try
            {
                var draft = Draft();
                if (openedSource == "saved" && String.Equals(openedName, draft.Text("name"), StringComparison.OrdinalIgnoreCase))
                    draft["revision"] = revision;
                int expectedVersion = deckVersion;
                var stored = Json.Object(await bridge.Call("save", draft));
                openedName = stored.Text("name");
                openedSource = stored.Text("source");
                revision = stored.Text("revision");
                if (expectedVersion == deckVersion) dirty = false;
                Status(openedName + ".ydk gespeichert.");
                await LoadLibrary();
            }
            finally { loadingDeck = false; Button("SaveDeck").IsEnabled = true; }
        }

        private async Task ExportDeck(string kind)
        {
            var draft = Draft();
            draft["kind"] = kind;
            SaveFile(Json.Object(await bridge.Call("export", draft)),
                kind == "ydk" ? "Yu-Gi-Oh!-Decks|*.ydk" : "Textdatei|*.txt");
        }

        private void SaveFile(Dictionary<string, object> file, string filter)
        {
            var dialog = new SaveFileDialog { FileName = file.Text("name"), Filter = filter, AddExtension = true };
            if (dialog.ShowDialog(window) != true) return;
            File.WriteAllText(dialog.FileName, file.Text("content"), new UTF8Encoding(false));
            Status(Path.GetFileName(dialog.FileName) + " exportiert.");
        }

        private void RenderDeck(long? selection)
        {
            var rows = sections[zone].GroupBy(code => code).Select(group =>
            {
                var card = cards[group.Key];
                card.Quantity = group.Count();
                card.Locked = locks.Contains(card.Code);
                return card;
            }).ToList();
            Table("DeckCards").ItemsSource = rows;
            Table("DeckCards").SelectedItem = rows.FirstOrDefault(item => item.Code == selection);
            for (int i = 0; i < Zones.Length; i++)
            {
                Button(ZoneButtons[i]).Content = ZoneLabels[i] + "  " + sections[Zones[i]].Count;
                Button(ZoneButtons[i]).Style = (Style)window.FindResource(Zones[i] == zone ? "PrimaryButton" : (object)typeof(Button));
            }
            Text("LockCount").Text = locks.Count + (locks.Count == 1 ? " Karte gesperrt" : " Karten gesperrt");
            UpdateCardControls();
        }

        private void UpdateCardControls()
        {
            var current = Table("DeckCards").SelectedItem as CardRow;
            foreach (var control in new[] { "DeckMinus", "DeckPlus", "ToggleLock", "MoveCard" })
                Button(control).IsEnabled = current != null;
            Button("ToggleLock").Content = current != null && locks.Contains(current.Code) ? "Karte entsperren" : "Karte sperren";
            var targets = new List<string>();
            if (current != null)
            {
                if (zone != "side") targets.Add("Side Deck");
                if (zone != current.Zone) targets.Add(ZoneLabels[Array.IndexOf(Zones, current.Zone)]);
            }
            Combo("MoveZone").ItemsSource = targets;
            Combo("MoveZone").SelectedIndex = 0;
        }

        private void Changed()
        {
            dirty = true;
            deckVersion++;
            Status("Ungespeicherte Änderungen");
            ScheduleCheck();
        }

        private void ChangeQuantity(int amount)
        {
            var selected = Table("DeckCards").SelectedItem as CardRow;
            if (selected == null) return;
            if (amount > 0) sections[zone].Add(selected.Code);
            else
            {
                sections[zone].RemoveAt(sections[zone].LastIndexOf(selected.Code));
                if (sections.Values.All(section => !section.Contains(selected.Code))) locks.Remove(selected.Code);
            }
            Changed();
            RenderDeck(selected.Code);
        }

        private void ToggleLock()
        {
            var card = Table("DeckCards").SelectedItem as CardRow;
            if (card == null) return;
            if (!locks.Add(card.Code)) locks.Remove(card.Code);
            Changed();
            RenderDeck(card.Code);
        }

        private void MoveCard()
        {
            var card = Table("DeckCards").SelectedItem as CardRow;
            int destination = Array.IndexOf(ZoneLabels, Choice("MoveZone"));
            if (card == null || destination < 0) return;
            sections[zone].RemoveAt(sections[zone].LastIndexOf(card.Code));
            zone = Zones[destination];
            sections[zone].Add(card.Code);
            Changed();
            RenderDeck(card.Code);
        }

        private void AddCard()
        {
            var card = Table("Catalogue").SelectedItem as CardRow;
            if (card == null) return;
            cards[card.Code] = card;
            zone = Choice("AddTarget") == "Side Deck" ? "side" : card.Zone;
            sections[zone].Add(card.Code);
            Changed();
            RenderDeck(card.Code);
        }

        private void ScheduleCheck()
        {
            if (!ready) return;
            deckVersion++;
            checkTimer.Stop();
            checkTimer.Start();
        }

        private async Task CheckDeck()
        {
            int version = deckVersion;
            var draft = Draft();
            if (String.IsNullOrWhiteSpace(draft.Text("name")))
            {
                Text("CheckSummary").Text = "Bitte einen Decknamen eingeben.";
                Text("CheckDetails").Text = "";
                return;
            }
            draft["format"] = Choice("EditorFormat");
            draft["banlist"] = Banlist("EditorBanlist");
            var result = Json.Object(await bridge.Call("check", draft));
            if (version != deckVersion) return;
            var groups = Json.Object(result["groups"]);
            var findings = groups.Values.SelectMany(value => (object[])value).Cast<string>().ToList();
            Text("CheckSummary").Text = result.Text("label") + " · " +
                (findings.Count == 0 ? "Prüfung bestanden" : findings.Count + (findings.Count == 1 ? " Befund" : " Befunde"));
            Text("CheckSummary").Foreground = new SolidColorBrush((Color)ColorConverter.ConvertFromString(
                findings.Count == 0 ? "#8FDEBB" : "#FFD098"));
            Text("CheckDetails").Text = String.Join(Environment.NewLine, findings.Select(line => "• " + line.Replace("`", "")));
        }

        private void ScheduleSearch(bool reset)
        {
            if (!ready) return;
            if (reset) offset = 0;
            searchVersion++;
            catalogTimer.Stop();
            catalogTimer.Start();
        }

        private async Task SearchCards()
        {
            int version = searchVersion;
            Button("PrevCards").IsEnabled = false;
            Button("NextCards").IsEnabled = false;
            string[] kinds = { "all", "monster", "extra", "spell", "trap" };
            var result = Json.Object(await bridge.Call("cards", Json.Fields("query", Field("CardQuery").Text,
                "kind", kinds[Combo("CardKind").SelectedIndex], "offset", offset,
                "format", Choice("EditorFormat"), "banlist", Banlist("EditorBanlist"))));
            if (version != searchVersion) return;
            var rows = result.Array("items").Select(value => new CardRow(Json.Object(value))).ToList();
            Table("Catalogue").ItemsSource = rows;
            Table("Catalogue").SelectedIndex = rows.Count > 0 ? 0 : -1;
            total = Convert.ToInt32(result["total"]);
            Text("CardCount").Text = total == 0 ? "Keine Karten gefunden" :
                String.Format(German, "{0}–{1} von {2:N0}", offset + 1, offset + rows.Count, total);
            Button("PrevCards").IsEnabled = offset > 0;
            Button("NextCards").IsEnabled = offset + 24 < total;
        }

        private void ShowPage(bool comparison)
        {
            Find<Grid>("EditorPage").Visibility = comparison ? Visibility.Collapsed : Visibility.Visible;
            Find<Grid>("ComparisonPage").Visibility = comparison ? Visibility.Visible : Visibility.Collapsed;
            Button("ShowEditor").Style = (Style)window.FindResource(comparison ? (object)typeof(Button) : "PrimaryButton");
            Button("ShowComparison").Style = (Style)window.FindResource(comparison ? "PrimaryButton" : (object)typeof(Button));
        }

        private void PlannedGames()
        {
            int blocks;
            int count = Find<ListBox>("Opponents").SelectedItems.Count;
            Text("PlannedGames").Text = count > 0 && Int32.TryParse(Field("Blocks").Text, out blocks) && blocks >= 1 && blocks <= 100
                ? (blocks * count * 4) + " Einzelduelle geplant" : "";
        }

        private void JobButtons(bool running)
        {
            jobBusy = running;
            Button("StartComparison").IsEnabled = !running;
            Button("CancelComparison").IsEnabled = running && jobId != null;
        }

        private async Task StartComparison()
        {
            if (jobBusy || !ready) return;
            var original = Combo("OriginalDeck").SelectedItem as DeckRef;
            var variant = Combo("VariantDeck").SelectedItem as DeckRef;
            var opponents = Find<ListBox>("Opponents").SelectedItems.Cast<DeckRef>().ToArray();
            int blocks;
            long seed;
            if (original == null || variant == null || opponents.Length == 0)
                throw new InvalidOperationException("Wähle Original, Variante und mindestens einen Gegner.");
            if (!Int32.TryParse(Field("Blocks").Text, out blocks) || !Int64.TryParse(Field("Seed").Text, out seed))
                throw new InvalidOperationException("Testblöcke und Seed müssen ganze Zahlen sein.");
            jobId = null;
            lastResult = null;
            JobButtons(true);
            Find<FrameworkElement>("Metrics").Visibility = Visibility.Collapsed;
            Button("ExportReport").IsEnabled = false;
            Button("ExportGames").IsEnabled = false;
            Text("ComparisonDetails").Text = "";
            Text("ComparisonProgress").Text = "Decks werden geprüft…";
            try
            {
                var data = Json.Fields("original", original.Data, "variant", variant.Data,
                    "opponents", opponents.Select(item => item.Data).ToArray(), "blocks", blocks,
                    "seed", seed, "format", Choice("CompareFormat"), "banlist", Banlist("CompareBanlist"));
                jobId = Json.Object(await bridge.Call("compare", data)).Text("id");
                JobButtons(true);
                jobTimer.Start();
                await PollComparison();
            }
            catch { JobButtons(false); Text("ComparisonProgress").Text = "Vergleich nicht gestartet."; throw; }
        }

        private async Task PollComparison()
        {
            if (polling || jobId == null) return;
            polling = true;
            try
            {
                var value = Json.Object(await bridge.Call("status", Json.Fields("id", jobId)));
                string status = value.Text("status");
                if (status == "running") { Text("ComparisonProgress").Text = value.Text("progress"); return; }
                jobTimer.Stop();
                JobButtons(false);
                lastResult = value.Get("result");
                if (lastResult != null) RenderComparison(Json.Object(lastResult));
                if (status == "error") Status(value.Text("error"));
                if (status == "cancelled") Text("ComparisonProgress").Text = "Der Testlauf wurde abgebrochen.";
            }
            catch { jobTimer.Stop(); JobButtons(false); throw; }
            finally { polling = false; }
        }

        private async Task CancelComparison()
        {
            if (jobId == null || !jobBusy) return;
            await bridge.Call("cancel", Json.Fields("id", jobId));
            await PollComparison();
        }

        private static string Rate(Dictionary<string, object> counts)
        {
            int total = counts.Values.Sum(value => Convert.ToInt32(value));
            return total == 0 ? "—" : (100.0 * Convert.ToInt32(counts["win"]) / total).ToString("0.0", German) + " %";
        }

        private static string Delta(object value)
        {
            return value == null ? "—" : (100 * Convert.ToDouble(value)).ToString("+0.0;-0.0;0.0", German) + " Pp.";
        }

        private void RenderComparison(Dictionary<string, object> record)
        {
            var result = Json.Object(record["summary"]);
            var names = record.Array("decks");
            Text("ComparisonProgress").Text = names[0] + " (A) · " + names[1] + " (B)" +
                Environment.NewLine + record.Text("rules") + " · " + result["cases"] + " gewertete Duelle je Variante";
            Text("WinRateA").Text = Rate(Json.Object(result["original"]));
            Text("WinRateB").Text = Rate(Json.Object(result["variant"]));
            Text("Difference").Text = Delta(result.Get("delta"));
            Find<FrameworkElement>("Metrics").Visibility = Visibility.Visible;
            var details = new List<string>();
            var interval = result.Get("interval") as object[];
            if (interval != null)
                details.Add("95-%-Intervall der Differenz von " + Delta(interval[0]) + " bis " + Delta(interval[1]) + ".");
            else
                details.Add("Zu wenige vollständige Testblöcke für ein Unsicherheitsintervall.");
            int excluded = Convert.ToInt32(result["blocks"]) - Convert.ToInt32(result["valid_blocks"]);
            if (excluded > 0) details.Add(excluded + " Blöcke wegen Duellfehlern ausgeschlossen.");
            details.Add("");
            details.Add("Deckänderungen");
            foreach (var change in record.Array("changes").Select(Json.Object))
                details.Add("• " + change.Text("zone") + " Deck · " +
                    Convert.ToInt32(change["delta"]).ToString("+0;-0", German) + " " + change.Text("card"));
            if (record.Array("changes").Length == 0) details.Add("Identische Kartenzusammensetzung.");
            details.Add("");
            details.Add("Siegquote A / B je Gegner und Startposition");
            foreach (var opponent in result.Array("opponents").Select(Json.Object))
                foreach (var position in opponent.Array("positions").Select(Json.Object))
                    details.Add(names[2 + Convert.ToInt32(opponent["index"])] + " · " +
                        (Convert.ToBoolean(position["start"]) ? "Beginnt" : "Zieht nach") + " · " +
                        Rate(Json.Object(position["A"])) + " / " + Rate(Json.Object(position["B"])));
            if (record.Get("judge") is Dictionary<string, object>)
            {
                var judge = Json.Object(record["judge"]);
                details.Add("");
                details.Add("Judge-Auswertung");
                details.Add(judge["chains"] + " abgeschlossene Ketten geprüft · " +
                    judge["escalations"] + " Duelle zur Nachprüfung an den Headjudge");
                foreach (var review in judge.Array("reviews").Take(4).Select(Json.Object))
                    details.Add(review.Text("replay") + " · " + review.Text("status"));
            }
            Text("ComparisonDetails").Text = String.Join(Environment.NewLine, details);
            Button("ExportReport").IsEnabled = true;
            Button("ExportGames").IsEnabled = true;
        }

        private async Task ExportReport(string kind, string filter)
        {
            if (jobId == null) return;
            SaveFile(Json.Object(await bridge.Call("report", Json.Fields("id", jobId, "kind", kind))), filter);
        }

        private void Screenshot(string path)
        {
            window.UpdateLayout();
            var root = (FrameworkElement)window.Content;
            var bitmap = new RenderTargetBitmap((int)Math.Ceiling(root.ActualWidth),
                (int)Math.Ceiling(root.ActualHeight), 96, 96, PixelFormats.Pbgra32);
            bitmap.Render(root);
            var encoder = new PngBitmapEncoder();
            encoder.Frames.Add(BitmapFrame.Create(bitmap));
            using (var file = File.Create(path)) encoder.Save(file);
        }

        private static void Expect(bool ok, string message)
        {
            if (!ok) throw new InvalidOperationException(message);
        }

        private async Task WaitForJob()
        {
            var clock = Stopwatch.StartNew();
            while (jobBusy && clock.ElapsedMilliseconds < 25000)
            {
                await Task.Delay(180);
                await PollComparison();
            }
            Expect(!jobBusy, "Vergleich hat das Zeitlimit der Prüfung erreicht.");
        }

        private async Task SelfTest(string directory)
        {
            Expect(sections["main"].Count == 45, "HERO wurde nicht richtig geladen.");
            Expect(Text("CheckSummary").Text.Contains("Befunde"), "Die TCG-Prüfung wurde nicht angezeigt.");
            Screenshot(Path.Combine(directory, "editor.png"));
            Field("CardQuery").Text = "46986414";
            catalogTimer.Stop();
            await SearchCards();
            Expect(Table("Catalogue").Items.Count == 1, "Kartensuche fehlgeschlagen.");
            AddCard();
            ToggleLock();
            Expect(locks.Contains(46986414), "Kartensperre fehlgeschlagen.");
            MoveCard();
            Expect(sections["side"].Contains(46986414) && locks.Contains(46986414), "Verschieben fehlgeschlagen.");
            MoveCard();
            Field("DeckName").Text = "Nativer Prüflauf " + Guid.NewGuid().ToString("N").Substring(0, 8);
            var payload = Draft();
            payload["kind"] = "ydk";
            var ydk = Json.Object(await bridge.Call("export", payload));
            payload["kind"] = "txt";
            var txt = Json.Object(await bridge.Call("export", payload));
            Expect(txt.Text("content").Contains("Dark Magician") && ydk.Text("content").Contains("#locked 46986414"),
                "Deckexport fehlgeschlagen.");
            await ImportDeck(Field("DeckName").Text, ydk.Text("content"));
            Expect(locks.Contains(46986414) && sections["main"].Count == 46, "Wiederimport fehlgeschlagen.");
            await SaveDeck();
            var original = MatchDeck("HERO", "original");
            var variant = MatchDeck(openedName, "saved");
            var opponent = MatchDeck("D Link", "original");
            Expect(original != null && variant != null && opponent != null, "Gespeichertes Deck fehlt.");
            await OpenDeck(variant);
            Expect(locks.Contains(46986414), "Kartensperre fehlt nach Wiederöffnen.");
            ShowPage(true);
            Combo("OriginalDeck").SelectedItem = original;
            Combo("VariantDeck").SelectedItem = variant;
            Find<ListBox>("Opponents").SelectedItems.Add(opponent);
            Field("Blocks").Text = "1";
            bool blocked = false;
            try { await StartComparison(); }
            catch (InvalidOperationException e) { blocked = e.Message.Contains("Vergleich nicht gestartet"); }
            Expect(blocked, "Eine durch die Banliste ungültige Liste wurde gestartet.");
            Combo("CompareFormat").SelectedItem = "Vorschau";
            await StartComparison();
            await WaitForJob();
            Expect(lastResult != null && Text("ComparisonProgress").Text.Contains("2 gewertete Duelle je Variante"),
                "Ausgewerteter Vergleich fehlt.");
            var report = Json.Object(await bridge.Call("report", Json.Fields("id", jobId, "kind", "bericht")));
            Expect(report.Text("content").Contains("Dark Magician"), "Testbericht enthält den Deckwechsel nicht.");
            Expect(Text("ComparisonDetails").Text.Contains("abgeschlossene Ketten geprüft") &&
                report.Text("content").Contains("Konami-Regelbuch"), "Judge-Auswertung fehlt.");
            Screenshot(Path.Combine(directory, "vergleich.png"));
            Field("Blocks").Text = "50";
            await StartComparison();
            await CancelComparison();
            await WaitForJob();
            Expect(Text("ComparisonProgress").Text.Contains("abgebrochen"), "Vergleich ließ sich nicht abbrechen.");
            File.WriteAllText(Path.Combine(directory, "ok.txt"), "Native Oberfläche, Deckprüfung, Import, Export, Kartensperre, Vergleich und Abbruch erfolgreich.");
            dirty = false;
        }
    }

    static class Program
    {
        private static string Argument(string[] args, string option)
        {
            int index = Array.IndexOf(args, option);
            return index >= 0 && index + 1 < args.Length ? Path.GetFullPath(args[index + 1]) : null;
        }

        [STAThread]
        public static int Main(string[] args)
        {
            string root = Argument(args, "--root") ?? AppDomain.CurrentDomain.BaseDirectory;
            string test = Argument(args, "--self-test");
            if (test != null) Directory.CreateDirectory(test);
            try
            {
                var app = new Application();
                Window window;
                using (var xaml = Assembly.GetExecutingAssembly().GetManifestResourceStream("MainWindow.xaml"))
                    window = (Window)XamlReader.Load(xaml);
                if (test != null)
                {
                    window.WindowStartupLocation = WindowStartupLocation.Manual;
                    window.Left = -15000;
                    window.ShowActivated = false;
                    window.ShowInTaskbar = false;
                }
                using (var bridge = new Bridge(root, test))
                {
                    new Desktop(window, bridge, test);
                    return app.Run(window);
                }
            }
            catch (Exception error)
            {
                if (test != null) File.WriteAllText(Path.Combine(test, "error.txt"), error.ToString());
                else MessageBox.Show("YGO KI APP konnte nicht geöffnet werden.\n" + error.Message, "YGO KI APP", MessageBoxButton.OK, MessageBoxImage.Error);
                return 1;
            }
        }
    }
}
