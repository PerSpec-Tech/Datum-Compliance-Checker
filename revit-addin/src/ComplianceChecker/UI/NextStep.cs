using Autodesk.Revit.UI;

namespace ComplianceChecker.UI
{
    /// <summary>
    /// After each step, say plainly what happened and offer the next one (1 Pair → 2 Site Setup →
    /// 3 Run Check), so nobody is left wondering which button comes next.
    /// </summary>
    internal static class NextStep
    {
        /// <returns>true if the user chose to go to the next step now.</returns>
        public static bool Offer(string title, string done, string next, string nextDetail)
        {
            var dialog = new TaskDialog("Datum")
            {
                MainInstruction = title,
                MainContent = done,
                CommonButtons = TaskDialogCommonButtons.Close,
            };
            dialog.AddCommandLink(TaskDialogCommandLinkId.CommandLink1, next, nextDetail);
            dialog.DefaultButton = TaskDialogResult.CommandLink1; // only after the link exists
            return dialog.Show() == TaskDialogResult.CommandLink1;
        }

        /// <returns>CommandLink1 = do the missing step, CommandLink2 = continue anyway, else cancel.</returns>
        public static TaskDialogResult Missing(string title, string why, string fix, string fixDetail, string anyway, string anywayDetail)
        {
            var dialog = new TaskDialog("Datum")
            {
                MainInstruction = title,
                MainContent = why,
                CommonButtons = TaskDialogCommonButtons.Cancel,
            };
            dialog.AddCommandLink(TaskDialogCommandLinkId.CommandLink1, fix, fixDetail);
            if (!string.IsNullOrEmpty(anyway) && anyway != "Cancel")
                dialog.AddCommandLink(TaskDialogCommandLinkId.CommandLink2, anyway, anywayDetail);
            dialog.DefaultButton = TaskDialogResult.CommandLink1; // only after the link exists
            return dialog.Show();
        }
    }
}
