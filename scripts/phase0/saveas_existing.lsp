;; Q: what does _.SAVEAS do when the target already exists?
(add-line)
(command "_.SAVEAS" "" (strcat *dir* "target.dwg"))
(setq *size1* (vl-file-size (strcat *dir* "target.dwg")))
(command "_.SAVEAS" "" (strcat *dir* "current.dwg"))
(repeat 200 (add-line))
(log-kv "before" (list (state) *size1*))

(safe "saveas-onto-existing"
  (function (lambda () (command "_.SAVEAS" "" (strcat *dir* "target.dwg")) (state))))
(log-kv "after-first-call" (state))
(if (> (getvar "CMDACTIVE") 0)
  (progn
    (log-kv "prompted-for" (getvar "LASTPROMPT"))
    (command "_Y")
    (log-kv "after-yes" (state))
  )
)
(log-kv "size-after" (vl-file-size (strcat *dir* "target.dwg")))
(log-kv "bak-exists" (findfile (strcat *dir* "target.bak")))
(finish)
