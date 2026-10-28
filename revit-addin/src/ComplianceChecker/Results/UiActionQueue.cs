using System;
using System.Collections.Concurrent;
using Autodesk.Revit.UI;

namespace ComplianceChecker.Results
{
    /// <summary>
    /// The only way background code reaches the Revit API: queue an action, raise one ExternalEvent,
    /// and Revit runs it on its main thread when it's idle (P5.6).
    /// </summary>
    public sealed class UiActionQueue : IExternalEventHandler, IDisposable
    {
        private readonly ConcurrentQueue<Action<UIApplication>> _queue = new();
        private readonly ExternalEvent _event;

        /// <summary>Must be created in a valid Revit API context (e.g. OnStartup).</summary>
        public UiActionQueue() => _event = ExternalEvent.Create(this);

        public void Post(Action<UIApplication> action)
        {
            _queue.Enqueue(action);
            _event.Raise();
        }

        public void Execute(UIApplication app)
        {
            while (_queue.TryDequeue(out var action))
            {
                try
                {
                    action(app);
                }
                catch (Exception e)
                {
                    TaskDialog.Show("Datum", "Something went wrong applying the results:\n" + e.Message);
                }
            }
        }

        public string GetName() => "Datum";

        public void Dispose() => _event.Dispose();
    }
}
