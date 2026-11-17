using System;
using System.Collections.Concurrent;
using System.Globalization;
using System.IO;
using System.Net;
using System.Net.Http;
using System.Threading;
using System.Threading.Tasks;
using System.Windows.Media.Imaging;

namespace YgoKi
{
    sealed class CardImages
    {
        private const int Limit = 2 * 1024 * 1024;
        private readonly string directory;
        private readonly bool online;
        private readonly SemaphoreSlim downloads = new SemaphoreSlim(4);
        private readonly ConcurrentDictionary<long, Lazy<Task<string>>> pending =
            new ConcurrentDictionary<long, Lazy<Task<string>>>();
        private readonly ConcurrentDictionary<long, DateTime> missing = new ConcurrentDictionary<long, DateTime>();
        private static readonly HttpClient Client = CreateClient();

        public CardImages(string directory, bool online)
        {
            this.directory = directory;
            this.online = online;
        }

        private static HttpClient CreateClient()
        {
            var client = new HttpClient(new HttpClientHandler { AllowAutoRedirect = false });
            client.Timeout = TimeSpan.FromSeconds(10);
            client.DefaultRequestHeaders.UserAgent.ParseAdd("YGOKI-Desktop/1.0");
            return client;
        }

        public async Task<BitmapImage> Load(long code, int width)
        {
            if (code <= 0 || code > UInt32.MaxValue) return null;
            string file = await Find(code).ConfigureAwait(false);
            return file == null ? null : await Task.Run(() => ReadImage(file, width)).ConfigureAwait(false);
        }

        private async Task<string> Find(long code)
        {
            string stem = Path.Combine(directory, code.ToString(CultureInfo.InvariantCulture));
            if (File.Exists(stem + ".png")) return stem + ".png";
            if (File.Exists(stem + ".jpg")) return stem + ".jpg";
            DateTime retry;
            if (!online || (missing.TryGetValue(code, out retry) && retry > DateTime.UtcNow)) return null;

            var item = pending.GetOrAdd(code, number =>
                new Lazy<Task<string>>(() => Download(number, stem + ".jpg")));
            try { return await item.Value.ConfigureAwait(false); }
            finally
            {
                Lazy<Task<string>> removed;
                if (pending.TryGetValue(code, out removed) && ReferenceEquals(removed, item))
                    pending.TryRemove(code, out removed);
            }
        }

        private async Task<string> Download(long code, string path)
        {
            await downloads.WaitAsync().ConfigureAwait(false);
            string temporary = null;
            try
            {
                string url = "https://images.ygoprodeck.com/images/cards/" +
                    code.ToString(CultureInfo.InvariantCulture) + ".jpg";
                using (var response = await Client.GetAsync(url, HttpCompletionOption.ResponseHeadersRead).ConfigureAwait(false))
                {
                    if (!response.IsSuccessStatusCode)
                    {
                        missing[code] = DateTime.UtcNow.AddSeconds(response.StatusCode == HttpStatusCode.NotFound ? 900 : 30);
                        return null;
                    }
                    if (response.Content.Headers.ContentLength > Limit) return null;
                    using (var buffer = new MemoryStream())
                    using (var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(10)))
                    using (var stream = await response.Content.ReadAsStreamAsync().ConfigureAwait(false))
                    {
                        var block = new byte[16384];
                        int length;
                        while ((length = await stream.ReadAsync(block, 0, block.Length, timeout.Token).ConfigureAwait(false)) > 0)
                        {
                            if (buffer.Length + length > Limit) return null;
                            buffer.Write(block, 0, length);
                        }
                        if (buffer.Length < 4 || buffer.GetBuffer()[0] != 255 || buffer.GetBuffer()[1] != 216)
                            return null;
                        Directory.CreateDirectory(directory);
                        temporary = path + "." + Guid.NewGuid().ToString("N") + ".tmp";
                        File.WriteAllBytes(temporary, buffer.ToArray());
                        if (ReadImage(temporary, 64) == null) return null;
                        try { File.Move(temporary, path); }
                        catch (IOException) { if (!File.Exists(path)) throw; }
                    }
                }
                return path;
            }
            catch (Exception error)
            {
                if (!(error is IOException || error is UnauthorizedAccessException ||
                      error is HttpRequestException || error is OperationCanceledException)) throw;
                missing[code] = DateTime.UtcNow.AddSeconds(30);
                return null;
            }
            finally
            {
                if (temporary != null)
                    try { File.Delete(temporary); }
                    catch (IOException) { }
                    catch (UnauthorizedAccessException) { }
                downloads.Release();
            }
        }

        private static BitmapImage ReadImage(string file, int width)
        {
            try
            {
                using (var stream = File.OpenRead(file))
                {
                    if (stream.Length > Limit) return null;
                    var image = new BitmapImage();
                    image.BeginInit();
                    image.StreamSource = stream;
                    image.CacheOption = BitmapCacheOption.OnLoad;
                    if (width > 0) image.DecodePixelWidth = width;
                    image.EndInit();
                    image.Freeze();
                    return image;
                }
            }
            catch (Exception error)
            {
                if (!(error is IOException || error is UnauthorizedAccessException ||
                      error is NotSupportedException || error is ArgumentException || error is FormatException ||
                      error is InvalidOperationException)) throw;
                return null;
            }
        }
    }
}
