# 可自定义 lupdate 路径，默认使用 'lupdate'（需在 PATH 中）
$lupdatePath = "lupdate"

# 获取根目录下所有 .py 文件
$pyFiles = Get-ChildItem -Path . -Filter *.py -File

# 获取 view 及其子目录下所有 .ui 文件
$uiFiles = Get-ChildItem -Path ./view -Filter *.ui -File -Recurse

# 合并所有文件路径
$allFiles = @()
if ($pyFiles.Count -gt 0) {
    $allFiles += $pyFiles.FullName
}
if ($uiFiles.Count -gt 0) {
    $allFiles += $uiFiles.FullName
}

# 遍历 ./i18n 目录下所有 .ts 文件，批量更新
$tsFiles = Get-ChildItem -Path ./i18n -Filter *.ts -File
foreach ($tsFile in $tsFiles) {
    if ($allFiles.Count -gt 0) {
        & $lupdatePath $allFiles -ts $tsFile.FullName
    }
}
