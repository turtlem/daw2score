-- daw2score: open the export window on the current REAPER project (Windows and macOS).
-- Install: in REAPER, Actions > Show action list > New action > Load ReaScript..., pick this file.
--   Windows: it is in the daw2score install folder, subfolder "reaper".
--   macOS: it is on the daw2score disk image; daw2score.app must be in /Applications or ~/Applications.
-- Assign it a shortcut or a toolbar button if you like.

local function dir_of(path) return path:match("^(.*)[\\/]") end
local function msg(text) reaper.ShowMessageBox(text, "daw2score", 0) end

local _, rpp = reaper.EnumProjects(-1)
if rpp == nil or rpp == "" then
  msg("Save the project first: daw2score reads the saved .rpp file.")
  return
end
if reaper.IsProjectDirty(0) == 1 then
  local r = reaper.ShowMessageBox("The project has unsaved changes. Save before exporting?", "daw2score", 3)
  if r == 2 then return end          -- cancel
  if r == 6 then reaper.Main_SaveProject(0, false) end
end

if reaper.GetOS():match("^Win") then
  local script = debug.getinfo(1, "S").source:gsub("^@", "")
  local candidates = {
    dir_of(dir_of(script)) .. "\\daw2score.exe",                          -- script left in the install folder
    (os.getenv("LOCALAPPDATA") or "") .. "\\Programs\\daw2score\\daw2score.exe",
    (os.getenv("ProgramFiles") or "") .. "\\daw2score\\daw2score.exe",
  }
  for _, exe in ipairs(candidates) do
    if reaper.file_exists(exe) then
      reaper.ExecProcess('"' .. exe .. '" "' .. rpp .. '"', -1)  -- -1: do not wait
      return
    end
  end
  msg("daw2score.exe not found. Reinstall daw2score, or load this script from its install folder.")
else
  local candidates = { "/Applications/daw2score.app", (os.getenv("HOME") or "") .. "/Applications/daw2score.app" }
  for _, app in ipairs(candidates) do
    if reaper.file_exists(app .. "/Contents/MacOS/daw2score") then
      reaper.ExecProcess('/usr/bin/open -n -a "' .. app .. '" --args "' .. rpp .. '"', -1)
      return
    end
  end
  msg("daw2score.app not found in /Applications or ~/Applications.")
end
