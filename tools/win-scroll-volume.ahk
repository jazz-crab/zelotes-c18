#Requires AutoHotkey v2.0
#SingleInstance Force

; Win + колесо мыши -> громкость.
;
; Мышь отправляет обычный HID-скролл, поэтому это работает поверх любой мыши
; и ничего не прошивает. Win+Scroll по умолчанию в Windows не занят.
;
; Ограничения: приложения с raw input (часть игр) и окна, запущенные от
; администратора, не увидят хоткей, если сам AutoHotkey не запущен elevated.

#WheelUp::Send "{Volume_Up}"
#WheelDown::Send "{Volume_Down}"
