<#
.SYNOPSIS
    BTC Quant Terminal V6.1 — Backtest Engine (PowerShell)
    Configuración V6.1: SL=700 | TP1=1000(75%) | TP2=1500(25%)
    BE=400pts | MaxHold=5velas | Score>=68 | Fee=35pts
    Bankroll=$5,000 | Notional=$20,000 | Leverage=20x
#>

Set-StrictMode -Off
$ErrorActionPreference = 'Continue'

# ─── CONFIGURACIÓN ────────────────────────────────────────────────────────────
$CFG = @{
    tp1_pts             = 1000
    tp2_pts             = 1500
    sl_pts              = 700
    tp1_partial_pct     = 0.75
    tp2_runner_pct      = 0.25
    break_even_lock_pts = 400
    max_hold_candles    = 5
    friction_fee_pts    = 35
    bankroll_usdt       = 5000.0
    trade_notional_usdt = 20000.0
    leverage            = 20
    min_score_threshold = 68
}

# ─── FETCH DATA ────────────────────────────────────────────────────────────────
Write-Host "[*] Descargando 600 velas 4H BTCUSDT desde Binance..." -ForegroundColor Cyan
$url = "https://data-api.binance.vision/api/v3/klines?symbol=BTCUSDT&interval=4h&limit=600"
try {
    $resp = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 20
    $raw = $resp.Content | ConvertFrom-Json
    Write-Host "[*] $($raw.Count) velas recibidas." -ForegroundColor Green
} catch {
    Write-Host "[ERROR] Fallo al conectar con Binance: $_" -ForegroundColor Red
    exit 1
}

# Convertir a objetos
$klines = @()
foreach ($k in $raw) {
    $klines += [PSCustomObject]@{
        t = [long]$k[0]; o = [double]$k[1]; h = [double]$k[2]
        l = [double]$k[3]; c = [double]$k[4]; v = [double]$k[5]
    }
}
# Usar últimas 500 velas
$klines = $klines | Select-Object -Last 500
Write-Host "[*] Usando $($klines.Count) velas para backtest." -ForegroundColor Cyan

# ─── INDICADORES ──────────────────────────────────────────────────────────────
function Calc-TR($h, $l, $prevC) {
    if ($null -eq $prevC) { return $h - $l }
    return [Math]::Max($h - $l, [Math]::Max([Math]::Abs($h - $prevC), [Math]::Abs($l - $prevC)))
}

function Calc-ATR($kl, $period = 14) {
    if ($kl.Count -lt ($period + 1)) { return 500.0 }
    $atr = 0.0
    for ($i = 1; $i -le $period; $i++) { $atr += Calc-TR $kl[$i].h $kl[$i].l $kl[$i-1].c }
    $atr /= $period
    for ($i = $period + 1; $i -lt $kl.Count; $i++) {
        $atr = ($atr * ($period - 1) + (Calc-TR $kl[$i].h $kl[$i].l $kl[$i-1].c)) / $period
    }
    return $atr
}

function Calc-EMA($values, $period) {
    if ($values.Count -eq 0) { return @() }
    $k = 2.0 / ($period + 1)
    $ema = @(0.0) * $values.Count
    $n = [Math]::Min($period, $values.Count)
    $sum = 0.0; for ($i = 0; $i -lt $n; $i++) { $sum += $values[$i] }
    $ema[$n-1] = $sum / $n
    for ($i = $n; $i -lt $values.Count; $i++) {
        $ema[$i] = $values[$i] * $k + $ema[$i-1] * (1 - $k)
    }
    return $ema
}

function Calc-Choppiness($kl, $period = 14) {
    if ($kl.Count -le $period) { return 50.0 }
    $trSum = 0.0; $maxH = -1e18; $minL = 1e18
    $start = $kl.Count - $period
    for ($i = $start; $i -lt $kl.Count; $i++) {
        $prevC = if ($i -gt 0) { $kl[$i-1].c } else { $kl[$i].o }
        $trSum += Calc-TR $kl[$i].h $kl[$i].l $prevC
        if ($kl[$i].h -gt $maxH) { $maxH = $kl[$i].h }
        if ($kl[$i].l -lt $minL) { $minL = $kl[$i].l }
    }
    $rng = $maxH - $minL
    if ($rng -le 0) { return 50.0 }
    $val = 100.0 * ([Math]::Log10($trSum / $rng) / [Math]::Log10($period))
    return [Math]::Min(100, [Math]::Max(0, $val))
}

function Calc-ADX($kl, $period = 14) {
    if ($kl.Count -le ($period * 2)) { return 25.0 }
    $tr = @(); $plusDM = @(); $minusDM = @()
    for ($i = 1; $i -lt $kl.Count; $i++) {
        $hd = $kl[$i].h - $kl[$i-1].h; $ld = $kl[$i-1].l - $kl[$i].l
        $plusDM  += if ($hd -gt $ld -and $hd -gt 0) { $hd } else { 0.0 }
        $minusDM += if ($ld -gt $hd -and $ld -gt 0) { $ld } else { 0.0 }
        $tr += Calc-TR $kl[$i].h $kl[$i].l $kl[$i-1].c
    }
    $trS = ($tr[0..($period-1)] | Measure-Object -Sum).Sum
    $pS  = ($plusDM[0..($period-1)] | Measure-Object -Sum).Sum
    $mS  = ($minusDM[0..($period-1)] | Measure-Object -Sum).Sum
    $dxArr = @()
    for ($i = $period; $i -lt $tr.Count; $i++) {
        $trS = $trS - $trS/$period + $tr[$i]
        $pS  = $pS  - $pS/$period  + $plusDM[$i]
        $mS  = $mS  - $mS/$period  + $minusDM[$i]
        $pdi = if ($trS -gt 0) { $pS/$trS*100 } else { 0.0 }
        $mdi = if ($trS -gt 0) { $mS/$trS*100 } else { 0.0 }
        $dsum = $pdi + $mdi
        $dxArr += if ($dsum -gt 0) { [Math]::Abs($pdi-$mdi)/$dsum*100 } else { 0.0 }
    }
    if ($dxArr.Count -lt $period) { return 25.0 }
    $adx = ($dxArr[0..($period-1)] | Measure-Object -Sum).Sum / $period
    for ($i = $period; $i -lt $dxArr.Count; $i++) { $adx = ($adx*($period-1) + $dxArr[$i])/$period }
    return $adx
}

function Calc-VWAP($kl, $lookback = 96) {
    $sub = $kl | Select-Object -Last $lookback
    $cumPV = 0.0; $cumV = 0.0
    foreach ($k in $sub) { $tp = ($k.h+$k.l+$k.c)/3; $cumPV += $tp*$k.v; $cumV += $k.v }
    if ($cumV -gt 0) { return $cumPV/$cumV } else { return $kl[-1].c }
}

function Calc-RSI($kl, $period = 14) {
    if ($kl.Count -le $period) { return 50.0 }
    $ag = 0.0; $al = 0.0
    for ($i = 1; $i -le $period; $i++) {
        $d = $kl[$i].c - $kl[$i-1].c
        if ($d -ge 0) { $ag += $d } else { $al -= $d }
    }
    $ag /= $period; $al /= $period
    for ($i = $period+1; $i -lt $kl.Count; $i++) {
        $d = $kl[$i].c - $kl[$i-1].c
        if ($d -ge 0) { $ag = ($ag*($period-1)+$d)/$period; $al = ($al*($period-1))/$period }
        else { $ag = ($ag*($period-1))/$period; $al = ($al*($period-1)-$d)/$period }
    }
    if ($al -eq 0) { return 100.0 }
    return 100.0 - (100.0 / (1.0 + $ag/$al))
}

function Calc-Ichimoku($kl, $tenkanP=9, $kijunP=26, $spanBP=52) {
    if ($kl.Count -lt $spanBP) { return $null }
    $midFn = { param($sub) (($sub | Measure-Object h -Max).Maximum + ($sub | Measure-Object l -Min).Minimum) / 2.0 }
    $n = $kl.Count
    $refIdx = [Math]::Max($spanBP, $n - 26)
    $spanA = (& $midFn $kl[($refIdx-$tenkanP)..($refIdx-1)]) + (& $midFn $kl[($refIdx-$kijunP)..($refIdx-1)])
    $spanA /= 2.0
    $spanB = & $midFn $kl[($refIdx-$spanBP)..($refIdx-1)]
    return @{
        kumo_top    = [Math]::Max($spanA, $spanB)
        kumo_bottom = [Math]::Min($spanA, $spanB)
    }
}

function Calc-TTMSqueeze($kl, $period=20, $bbMult=2.0, $kcMult=1.5) {
    if ($kl.Count -lt $period) { return @{ is_squeeze=$false; momentum=0.0 } }
    $sub = $kl | Select-Object -Last $period
    $closes = $sub | ForEach-Object { $_.c }
    $sma = ($closes | Measure-Object -Sum).Sum / $period
    $variance = ($closes | ForEach-Object { ($_ - $sma)*($_ - $sma) } | Measure-Object -Sum).Sum / $period
    $stdev = [Math]::Sqrt($variance)
    $atr = Calc-ATR $sub $period
    $is_sq = ($sma + $bbMult*$stdev) -lt ($sma + $kcMult*$atr) -and ($sma - $bbMult*$stdev) -gt ($sma - $kcMult*$atr)
    $maxH = ($sub | Measure-Object h -Max).Maximum
    $minL = ($sub | Measure-Object l -Min).Minimum
    $midPt = (($maxH + $minL)/2.0 + $sma) / 2.0
    return @{ is_squeeze=$is_sq; momentum=($sub[-1].c - $midPt) }
}

function Calc-OrderFlow($kl) {
    $deltas = @()
    foreach ($k in $kl) {
        $rng = $k.h - $k.l
        $buy  = if ($rng -gt 0) { ($k.c - $k.l)/$rng } else { 0.5 }
        $sell = if ($rng -gt 0) { ($k.h - $k.c)/$rng } else { 0.5 }
        $deltas += $k.v * ($buy - $sell)
    }
    $last3 = if ($deltas.Count -ge 3) { ($deltas | Select-Object -Last 3 | Measure-Object -Sum).Sum } else { 0.0 }
    $rvol = 1.0
    if ($kl.Count -ge 20) {
        $avg20 = ($kl | Select-Object -Last 20 | Measure-Object v -Average).Average
        if ($avg20 -gt 0) { $rvol = $kl[-1].v / $avg20 }
    }
    return @{ last3=$last3; rvol=$rvol }
}

# ─── EVALUATE SIGNAL ──────────────────────────────────────────────────────────
function Evaluate-Signal($kl) {
    if ($kl.Count -lt 50) { return $null }
    $cur = $kl[-1]; $curPrice = $cur.c

    # Session
    $dt = [DateTimeOffset]::FromUnixTimeMilliseconds($cur.t).UtcDateTime
    $utcH = $dt.Hour + $dt.Minute/60.0
    $isWknd = $dt.DayOfWeek -in @([DayOfWeek]::Saturday, [DayOfWeek]::Sunday)
    $isLondon = $utcH -ge 8.0 -and $utcH -lt 16.5
    $isNY = $utcH -ge 13.5 -and $utcH -lt 21.0
    $isOverlap = $isLondon -and $isNY
    $session = 'ASIAN'; $ss = 5
    if ($isOverlap) { $session = 'OVERLAP'; $ss = 15 }
    elseif ($isLondon) { $session = 'LONDON'; $ss = 12 }
    elseif ($isNY) { $session = 'NEWYORK'; $ss = 12 }
    if ($isWknd) { $ss = [Math]::Max(0, $ss-8) }
    $ss = [Math]::Min(15, $ss)

    $chop = Calc-Choppiness $kl 14
    $adx  = Calc-ADX $kl 14
    $ttm  = Calc-TTMSqueeze $kl 20
    $atr  = Calc-ATR $kl 14

    if ($chop -gt 61.8 -and $adx -lt 22.0) {
        return @{ score=0; direction='HIBERNATION'; session=$session; cur_price=$curPrice }
    }

    $grayZone = $false; $acs = 0
    if ($ttm.is_squeeze)                        { $acs = 4 }
    elseif ($adx -gt 25.0 -and $chop -lt 48.0) { $acs = 15 }
    elseif ($chop -lt 52.0)                     { $acs = 12 }
    elseif ($chop -ge 55.0 -and $chop -le 61.8 -and $adx -lt 20.0) { $acs = 4; $grayZone = $true }
    else                                         { $acs = 7 }
    $acs = [Math]::Min(15, $acs)

    # ORB simplified
    $rec30 = if ($kl.Count -gt 31) { $kl[($kl.Count-31)..($kl.Count-2)] } else { $kl }
    $orbHigh = ($rec30 | Measure-Object h -Max).Maximum
    $orbLow  = ($rec30 | Measure-Object l -Min).Minimum
    $lkb96 = if ($kl.Count -gt 97) { $kl[($kl.Count-97)..($kl.Count-2)] } else { $kl }
    $h24 = ($lkb96 | Measure-Object h -Max).Maximum
    $l24 = ($lkb96 | Measure-Object l -Min).Minimum
    $adrRem = [Math]::Max(0, 2500.0 - ($h24 - $l24))
    $orbScore = 0; $longOrb = $false; $shortOrb = $false
    if ($adrRem -gt 700) {
        $orbScore += 7
        if ($curPrice -gt $orbHigh) { $longOrb = $true; $orbScore += 8 }
        elseif ($curPrice -lt $orbLow) { $shortOrb = $true; $orbScore += 8 }
    } else { $orbScore = 2 }
    $orbScore = [Math]::Min(15, $orbScore)

    $vwap   = Calc-VWAP $kl 96
    $closes = $kl | ForEach-Object { $_.c }
    $ema20arr = Calc-EMA $closes 20; $ema20 = $ema20arr[-1]
    $ema50arr = Calc-EMA $closes 50; $ema50 = $ema50arr[-1]
    $ema100arr= Calc-EMA $closes 100; $ema100= $ema100arr[-1]
    $ema200arr= Calc-EMA $closes 200; $ema200= $ema200arr[-1]
    $rsi    = Calc-RSI $kl 14

    $slL = 0; $slS = 0
    if ($curPrice -gt $vwap -and $ema20 -gt $ema50)      { $slL += 10 }
    elseif ($curPrice -lt $vwap -and $ema20 -lt $ema50)  { $slS += 10 }
    $macroBull = $curPrice -gt $ema200 -and $ema100 -gt $ema200
    $macroBear = $curPrice -lt $ema200 -and $ema100 -lt $ema200
    if ($macroBull) { $slL += 8 } elseif ($macroBear) { $slS += 8 }

    $ichi = Calc-Ichimoku $kl
    $ibL = $false; $ibS = $false
    if ($null -ne $ichi) {
        if ($curPrice -gt $ichi.kumo_top)         { $slL += 7; $slS = [Math]::Max(0, $slS-18); $ibS = $true }
        elseif ($curPrice -lt $ichi.kumo_bottom)  { $slS += 7; $slL = [Math]::Max(0, $slL-18); $ibL = $true }
        else { $slL = [Math]::Max(0, $slL-6); $slS = [Math]::Max(0, $slS-6) }
    }

    if ($rsi -lt 35)     { $slL += 5 } elseif ($rsi -ge 40 -and $rsi -le 68) { $slL += 3 } elseif ($rsi -gt 80) { $slL -= 8 }
    if ($rsi -gt 75)     { $slS += 5 } elseif ($rsi -ge 32 -and $rsi -le 60) { $slS += 3 } elseif ($rsi -lt 20) { $slS -= 8 }

    $last3c = if ($kl.Count -ge 4) { $kl[($kl.Count-4)..($kl.Count-2)] } else { @() }
    if ($last3c.Count -ge 2) {
        $bullCount = ($last3c | Where-Object { $_.c -gt $_.o }).Count
        $bearCount = ($last3c | Where-Object { $_.c -lt $_.o }).Count
        if ($bullCount -ge 2) { $slL += 5 }
        if ($bearCount -ge 2) { $slS += 5 }
    }

    $dist20 = $curPrice - $ema20
    if ($dist20 -gt 1.1*$atr -or $rsi -gt 70) { $slL = [Math]::Max(0, $slL-10) }
    if ($dist20 -lt -1.1*$atr -or $rsi -lt 30) { $slS = [Math]::Max(0, $slS-10) }
    $slL = [Math]::Min(30, [Math]::Max(0, $slL))
    $slS = [Math]::Min(30, [Math]::Max(0, $slS))

    $of = Calc-OrderFlow $kl
    $cvd = $of.last3; $rvol = $of.rvol
    $ofL = if ($rvol -ge 1.2) { if ($cvd -gt 0) { 9 } else { 0 } } else { if ($cvd -gt 0) { 5 } else { 0 } }
    $ofS = if ($rvol -ge 1.2) { if ($cvd -lt 0) { 9 } else { 0 } } else { if ($cvd -lt 0) { 5 } else { 0 } }
    $ofL = [Math]::Min(15, [Math]::Max(0, $ofL))
    $ofS = [Math]::Min(15, [Math]::Max(0, $ofS))

    $liqL = 0; $liqS = 0
    if ($rec30.Count -gt 5) {
        $rh = ($rec30 | Measure-Object h -Max).Maximum
        $rl = ($rec30 | Measure-Object l -Min).Minimum
        if ($cur.l -lt $rl -and $cur.c -gt $rl) { $liqL = if ($macroBull -or $curPrice -gt $ema50) { 6 } else { 2 } }
        if ($cur.h -gt $rh -and $cur.c -lt $rh) { $liqS = if ($macroBear -or $curPrice -lt $ema50) { 6 } else { 2 } }
    }
    $liqL = [Math]::Min(6, $liqL); $liqS = [Math]::Min(6, $liqS)

    $totalL = $ss + $acs + $orbScore + $slL + $ofL + $liqL
    $totalS = $ss + $acs + $orbScore + $slS + $ofS + $liqS
    $isLongDom = $totalL -ge $totalS
    $score = [Math]::Min(100, [Math]::Round((if ($isLongDom) { $totalL } else { $totalS })))
    $thresh = $CFG.min_score_threshold

    $direction = 'NEUTRAL'
    if ($score -ge $thresh) { $direction = if ($isLongDom) { 'LONG' } else { 'SHORT' } }
    elseif ($score -ge 45)  { $direction = if ($isLongDom) { 'BIAS_LONG' } else { 'BIAS_SHORT' } }

    if ($direction -eq 'LONG'  -and $ibL) { $direction = 'NEUTRAL'; $score = [Math]::Min($score, 40) }
    if ($direction -eq 'SHORT' -and $ibS) { $direction = 'NEUTRAL'; $score = [Math]::Min($score, 40) }
    if ($direction -eq 'SHORT' -and $curPrice -gt $ema200) { $direction = 'NEUTRAL'; $score = [Math]::Min($score, 40) }
    if ($direction -eq 'LONG'  -and $curPrice -lt $ema200) { $direction = 'NEUTRAL'; $score = [Math]::Min($score, 40) }
    if ($ttm.is_squeeze -and $score -ge $thresh) {
        $direction = if ($isLongDom) { 'BIAS_LONG' } else { 'BIAS_SHORT' }; $score = $thresh - 5
    }
    if ([Math]::Abs($totalL-$totalS) -lt 8 -and $direction -in @('LONG','SHORT')) {
        $direction = if ($isLongDom) { 'BIAS_LONG' } else { 'BIAS_SHORT' }; $score = [Math]::Min($score, $thresh-3)
    }
    if ($grayZone -and $score -lt ($thresh+3) -and $direction -in @('LONG','SHORT')) {
        $direction = if ($isLongDom) { 'BIAS_LONG' } else { 'BIAS_SHORT' }; $score = $thresh-4
    }

    return @{
        score=$score; direction=$direction; session=$session; cur_price=$curPrice
        rsi=$rsi; chop=$chop; adx=$adx; atr=$atr
        ema20=$ema20; ema50=$ema50; ema200=$ema200; vwap=$vwap
    }
}

# ─── BACKTEST ENGINE ──────────────────────────────────────────────────────────
Write-Host "[*] Ejecutando backtest V6.1..." -ForegroundColor Cyan

$trades = [System.Collections.ArrayList]::new()
$equity = $CFG.bankroll_usdt
$equityCurve = [System.Collections.ArrayList]::new()
[void]$equityCurve.Add($equity)
$inTrade = $false; $entrySig = $null; $entryIdx = -1
$beTriggered = $false; $partialDone = $false
$WARMUP = 210

$tp1_pts = $CFG.tp1_pts; $tp2_pts = $CFG.tp2_pts; $sl_pts = $CFG.sl_pts
$tp1p = $CFG.tp1_partial_pct; $tp2p = $CFG.tp2_runner_pct
$be   = $CFG.break_even_lock_pts; $maxH = $CFG.max_hold_candles
$fee  = $CFG.friction_fee_pts; $notional = $CFG.trade_notional_usdt

for ($i = $WARMUP; $i -lt $klines.Count; $i++) {
    $window = $klines[0..$i]
    $sig = Evaluate-Signal $window
    if ($null -eq $sig) { [void]$equityCurve.Add($equity); continue }

    if ($inTrade) {
        $cur = $klines[$i]
        $isLong = ($entrySig.direction -eq 'LONG')
        $ep = $entrySig.cur_price
        $sl_price = $entrySig.sl_price
        $hold = $i - $entryIdx
        $tp1p_price = if ($isLong) { $ep + $tp1_pts } else { $ep - $tp1_pts }
        $tp2p_price = if ($isLong) { $ep + $tp2_pts } else { $ep - $tp2_pts }
        $outcome = $null; $pnlPts = $null

        if ($isLong) {
            if (-not $partialDone -and $cur.h -ge $tp1p_price) {
                $tp1Pnl = ($tp1p_price - $ep - $fee) * $tp1p
                $runnerSL = $ep + $be
                if ($cur.h -ge $tp2p_price) {
                    $tp2Pnl = ($tp2p_price - $ep - $fee) * $tp2p
                    $outcome = 'TP2'; $pnlPts = $tp1Pnl + $tp2Pnl
                } elseif ($cur.l -le $runnerSL) {
                    $tp2Pnl = ($runnerSL - $ep - $fee) * $tp2p
                    $outcome = 'TP1+BE'; $pnlPts = $tp1Pnl + $tp2Pnl
                } else {
                    $partialDone = $true; $beTriggered = $true; $entrySig.sl_price = $runnerSL
                    [void]$equityCurve.Add($equity); continue
                }
            } elseif ($partialDone) {
                if ($cur.h -ge $tp2p_price) {
                    $tp2Pnl = ($tp2p_price - $ep - $fee) * $tp2p; $outcome = 'TP2_RUNNER'; $pnlPts = $tp2Pnl
                } elseif ($cur.l -le $sl_price) {
                    $tp2Pnl = ($sl_price - $ep - $fee) * $tp2p; $outcome = 'TP1+BE'; $pnlPts = $tp2Pnl
                } elseif ($hold -ge $maxH) {
                    $tp2Pnl = ($cur.c - $ep - $fee) * $tp2p; $outcome = 'TIMEOUT_RUN'; $pnlPts = $tp2Pnl
                }
            } elseif ($cur.l -le $sl_price) {
                $pnlPts = -($sl_pts + $fee); $outcome = 'SL'
            } elseif ($hold -ge $maxH) {
                $pnlPts = ($cur.c - $ep - $fee); $outcome = 'TIMEOUT'
            }
        } else {
            if (-not $partialDone -and $cur.l -le $tp1p_price) {
                $tp1Pnl = ($ep - $tp1p_price - $fee) * $tp1p
                $runnerSL = $ep - $be
                if ($cur.l -le $tp2p_price) {
                    $tp2Pnl = ($ep - $tp2p_price - $fee) * $tp2p
                    $outcome = 'TP2'; $pnlPts = $tp1Pnl + $tp2Pnl
                } elseif ($cur.h -ge $runnerSL) {
                    $tp2Pnl = ($ep - $runnerSL - $fee) * $tp2p
                    $outcome = 'TP1+BE'; $pnlPts = $tp1Pnl + $tp2Pnl
                } else {
                    $partialDone = $true; $beTriggered = $true; $entrySig.sl_price = $runnerSL
                    [void]$equityCurve.Add($equity); continue
                }
            } elseif ($partialDone) {
                if ($cur.l -le $tp2p_price) {
                    $tp2Pnl = ($ep - $tp2p_price - $fee) * $tp2p; $outcome = 'TP2_RUNNER'; $pnlPts = $tp2Pnl
                } elseif ($cur.h -ge $sl_price) {
                    $tp2Pnl = ($ep - $sl_price - $fee) * $tp2p; $outcome = 'TP1+BE'; $pnlPts = $tp2Pnl
                } elseif ($hold -ge $maxH) {
                    $tp2Pnl = ($ep - $cur.c - $fee) * $tp2p; $outcome = 'TIMEOUT_RUN'; $pnlPts = $tp2Pnl
                }
            } elseif ($cur.h -ge $sl_price) {
                $pnlPts = -($sl_pts + $fee); $outcome = 'SL'
            } elseif ($hold -ge $maxH) {
                $pnlPts = ($ep - $cur.c - $fee); $outcome = 'TIMEOUT'
            }
        }

        if ($null -ne $outcome -and $null -ne $pnlPts) {
            $pnlUSD = $pnlPts * ($notional / $ep)
            $equity += $pnlUSD
            [void]$equityCurve.Add($equity)
            $entryDt = [DateTimeOffset]::FromUnixTimeMilliseconds($klines[$entryIdx].t).UtcDateTime.ToString('yyyy-MM-dd HH:mm')
            $exitDt  = [DateTimeOffset]::FromUnixTimeMilliseconds($klines[$i].t).UtcDateTime.ToString('yyyy-MM-dd HH:mm')
            [void]$trades.Add([PSCustomObject]@{
                entry_i=$entryIdx; exit_i=$i; direction=$entrySig.direction
                entry_price=$ep; exit_price=$klines[$i].c
                outcome=$outcome; pnl_pts=$pnlPts; pnl_usd=$pnlUSD; equity=$equity
                hold_candles=$hold; entry_date=$entryDt; exit_date=$exitDt
                score=$entrySig.score; rsi=$entrySig.rsi; chop=$entrySig.chop
            })
            $inTrade = $false; $entrySig = $null; $entryIdx = -1; $beTriggered = $false; $partialDone = $false
        } else {
            [void]$equityCurve.Add($equity)
        }
    }

    if (-not $inTrade -and $sig.direction -in @('LONG','SHORT')) {
        $inTrade = $true
        $slP = if ($sig.direction -eq 'LONG') { $sig.cur_price - $sl_pts } else { $sig.cur_price + $sl_pts }
        $entrySig = @{
            score=$sig.score; direction=$sig.direction; session=$sig.session
            cur_price=$sig.cur_price; sl_price=$slP; rsi=$sig.rsi; chop=$sig.chop
            partial_done=$false
        }
        $entryIdx = $i
        [void]$equityCurve.Add($equity)
    } elseif (-not $inTrade) {
        [void]$equityCurve.Add($equity)
    }
    # Progress cada 50 velas
    if ($i % 50 -eq 0) { Write-Host "  Procesando vela $i/$($klines.Count)..." -ForegroundColor DarkGray }
}

# ─── ANÁLISIS ─────────────────────────────────────────────────────────────────
Write-Host ""
if ($trades.Count -eq 0) {
    Write-Host "[!] Sin trades generados. Score threshold demasiado alto o datos insuficientes." -ForegroundColor Yellow
    exit 0
}

$initEq  = $CFG.bankroll_usdt
$finalEq = $equityCurve[-1]
$totalPnL = $finalEq - $initEq
$roi = ($totalPnL / $initEq) * 100.0

$wins  = @($trades | Where-Object { $_.pnl_usd -gt 0 })
$loses = @($trades | Where-Object { $_.pnl_usd -le 0 })
$tp2s  = @($trades | Where-Object { $_.outcome -like 'TP2*' })
$tp1be = @($trades | Where-Object { $_.outcome -like 'TP1+BE*' })
$sls   = @($trades | Where-Object { $_.outcome -eq 'SL' })
$touts = @($trades | Where-Object { $_.outcome -like 'TIMEOUT*' })
$longs = @($trades | Where-Object { $_.direction -eq 'LONG' })
$shrts = @($trades | Where-Object { $_.direction -eq 'SHORT' })
$total = $trades.Count

$winRate = if ($total -gt 0) { $wins.Count / $total * 100 } else { 0.0 }
$avgWin  = if ($wins.Count  -gt 0) { ($wins  | Measure-Object pnl_usd -Sum).Sum / $wins.Count  } else { 0.0 }
$avgLoss = if ($loses.Count -gt 0) { ($loses | Measure-Object pnl_usd -Sum).Sum / $loses.Count } else { 0.0 }
$rrRatio = if ($avgLoss -ne 0) { [Math]::Abs($avgWin / $avgLoss) } else { 9999.0 }

$peak = $initEq; $maxDD = 0.0
foreach ($eq in $equityCurve) {
    if ($eq -gt $peak) { $peak = $eq }
    $dd = if ($peak -gt 0) { ($peak - $eq) / $peak * 100 } else { 0 }
    if ($dd -gt $maxDD) { $maxDD = $dd }
}

$grossProfit = if ($wins.Count  -gt 0) { ($wins  | Measure-Object pnl_usd -Sum).Sum } else { 0.0 }
$grossLoss   = if ($loses.Count -gt 0) { [Math]::Abs(($loses | Measure-Object pnl_usd -Sum).Sum) } else { 0.0 }
$pf = if ($grossLoss -gt 0) { $grossProfit / $grossLoss } else { 9999.0 }
$avgHold = ($trades | Measure-Object hold_candles -Average).Average

$startDate = [DateTimeOffset]::FromUnixTimeMilliseconds($klines[0].t).UtcDateTime.ToString('yyyy-MM-dd')
$endDate   = [DateTimeOffset]::FromUnixTimeMilliseconds($klines[-1].t).UtcDateTime.ToString('yyyy-MM-dd')
$nDays = ($klines[-1].t - $klines[0].t) / (1000*3600*24)

$sep  = "═" * 65
$dash = "─" * 65

Write-Host ""
Write-Host $sep -ForegroundColor Cyan
Write-Host "  📊  BTC QUANT TERMINAL V6.1 — BACKTEST REPORT" -ForegroundColor Yellow
Write-Host "  Últimas 500 velas 4H  |  SL=700 TP1=1000(75%) TP2=1500(25%)" -ForegroundColor Gray
Write-Host $sep -ForegroundColor Cyan
Write-Host "  📅  Período: $startDate → $endDate ($([Math]::Round($nDays)) días)"
Write-Host "  💰  Bankroll Inicial:   `$$($initEq.ToString('N2'))"
Write-Host "  💰  Bankroll Final:     `$$($finalEq.ToString('N2'))"
$roiSign = if ($roi -ge 0) { "+" } else { "" }
$pnlSign = if ($totalPnL -ge 0) { "+" } else { "" }
Write-Host "  📈  ROI Total:          $($roiSign)$($roi.ToString('F2'))%  (`$$($pnlSign)$($totalPnL.ToString('F2')))" -ForegroundColor (if ($roi -ge 0) { 'Green' } else { 'Red' })
Write-Host "  📉  Max Drawdown:       $($maxDD.ToString('F2'))%" -ForegroundColor (if ($maxDD -gt 20) { 'Red' } elseif ($maxDD -gt 10) { 'Yellow' } else { 'Green' })
Write-Host "  ⚡  Profit Factor:      $($pf.ToString('F2'))x" -ForegroundColor (if ($pf -ge 1.5) { 'Green' } elseif ($pf -ge 1.0) { 'Yellow' } else { 'Red' })
Write-Host $dash -ForegroundColor DarkGray
Write-Host "  🔢  Total de Trades:    $total"
Write-Host "  ✅  Win Rate:           $($winRate.ToString('F1'))%  ($($wins.Count)W / $($loses.Count)L)" -ForegroundColor (if ($winRate -ge 55) { 'Green' } elseif ($winRate -ge 45) { 'Yellow' } else { 'Red' })
Write-Host "  🎯  TP2 Full:           $($tp2s.Count)  ($((($tp2s.Count/$total)*100).ToString('F1'))%)"
Write-Host "  🛡️  TP1+Break-Even:    $($tp1be.Count)  ($((($tp1be.Count/$total)*100).ToString('F1'))%)"
Write-Host "  🔴  Stop-Loss:          $($sls.Count)   ($((($sls.Count/$total)*100).ToString('F1'))%)"
Write-Host "  ⏱️  Timeout:            $($touts.Count)  ($((($touts.Count/$total)*100).ToString('F1'))%)"
Write-Host "  📊  Longs: $($longs.Count)  |  Shorts: $($shrts.Count)"
Write-Host $dash -ForegroundColor DarkGray
$avgWSign = if ($avgWin -ge 0) { "+" } else { "" }
Write-Host "  💚  Avg Ganancia:       `$$($avgWSign)$($avgWin.ToString('F2'))"
Write-Host "  ❤️  Avg Pérdida:       `$$($avgLoss.ToString('F2'))"
Write-Host "  ⚖️  Ratio R:R real:    $($rrRatio.ToString('F2')):1"
Write-Host "  ⏳  Hold Promedio:      $($avgHold.ToString('F1')) velas ($([Math]::Round($avgHold*4))h)"
Write-Host $dash -ForegroundColor DarkGray

Write-Host ""
Write-Host "  🏆  TOP 5 MEJORES TRADES:" -ForegroundColor Green
$trades | Sort-Object pnl_usd -Descending | Select-Object -First 5 | ForEach-Object {
    $sign = if ($_.pnl_usd -ge 0) { "+" } else { "" }
    Write-Host "    $($_.entry_date) $($_.direction.PadRight(5)) → $($_.outcome.PadRight(12))  PnL: `$$sign$($_.pnl_usd.ToString('F2').PadLeft(9))  (Score: $($_.score))" -ForegroundColor Green
}

Write-Host ""
Write-Host "  💀  TOP 5 PEORES TRADES:" -ForegroundColor Red
$trades | Sort-Object pnl_usd | Select-Object -First 5 | ForEach-Object {
    $sign = if ($_.pnl_usd -ge 0) { "+" } else { "" }
    Write-Host "    $($_.entry_date) $($_.direction.PadRight(5)) → $($_.outcome.PadRight(12))  PnL: `$$sign$($_.pnl_usd.ToString('F2').PadLeft(9))  (Score: $($_.score))" -ForegroundColor Red
}

Write-Host ""
Write-Host $sep -ForegroundColor Cyan
Write-Host "  📋  ANÁLISIS ROI Y MEJORAS SUGERIDAS" -ForegroundColor Yellow
Write-Host $sep -ForegroundColor Cyan

if ($winRate -lt 50) {
    Write-Host ""
    Write-Host "  🔧 Score Threshold:" -ForegroundColor Magenta
    Write-Host "    Win rate $($winRate.ToString('F1'))% < 50%. Subir min_score_threshold 68 → 72-75" -ForegroundColor White
    Write-Host "    para filtrar señales marginales y mejorar calidad de entradas."
}
if ($rrRatio -lt 1.5) {
    Write-Host ""
    Write-Host "  🔧 R:R Real Bajo ($($rrRatio.ToString('F2')):1):" -ForegroundColor Magenta
    Write-Host "    Opciones: (a) TP1: 1000→1200 pts, (b) SL: 700→600 pts,"
    Write-Host "    o (c) no cerrar 75% en TP1 — cerrar 50% y mover runner más lejos."
}
if (($sls.Count/$total) -gt 0.40) {
    Write-Host ""
    Write-Host "  🔧 SL Frecuente ($((($sls.Count/$total)*100).ToString('F0'))% de trades):" -ForegroundColor Magenta
    Write-Host "    SL de 700 pts puede ser estrecho en volatilidad actual (ATR elevado)."
    Write-Host "    Implementar SL dinámico: max(700, 1.0×ATR) con cap en 900 pts."
}
if (($tp2s.Count/$total) -lt 0.15) {
    Write-Host ""
    Write-Host "  🔧 TP2 Escaso ($((($tp2s.Count/$total)*100).ToString('F1'))% alcanza TP2):" -ForegroundColor Magenta
    Write-Host "    TP2 de 1500 pts captura pocas extensiones. Reducir a 1200 pts o"
    Write-Host "    aplicar trailing stop ATR×1.1 una vez TP1 alcanzado."
}
if ($pf -lt 1.5) {
    Write-Host ""
    Write-Host "  🔧 Profit Factor Bajo ($($pf.ToString('F2'))x):" -ForegroundColor Magenta
    Write-Host "    PF < 1.5x. Filtro de sesión estricto: OVERLAP+LONDON únicamente."
    Write-Host "    Bloquear señales en sesión ASIÁTICA cuando chop > 55."
}
if ($maxDD -gt 20) {
    Write-Host ""
    Write-Host "  ⚠️ Drawdown Alto ($($maxDD.ToString('F1'))%):" -ForegroundColor Red
    Write-Host "    Reducir notional a `$15,000 (x15) o pausar 24h tras 2 SL consecutivos."
    Write-Host "    Implementar circuit breaker: detener trading si DD intradiario > 8%."
}
if ($winRate -ge 55 -and $roi -gt 15 -and $maxDD -lt 15) {
    Write-Host ""
    Write-Host "  ✅ Sistema Sólido:" -ForegroundColor Green
    Write-Host "    ROI $($roiSign)$($roi.ToString('F1'))% con DD $($maxDD.ToString('F1'))%. Win rate saludable."
    Write-Host "    Considerar escalar notional a `$25,000 gradualmente (+`$2,500/semana)."
}

Write-Host ""
Write-Host "  📊  DISTRIBUCIÓN POR SESIÓN:" -ForegroundColor Cyan
$sessionStats = $trades | Group-Object { 
    $dt = [DateTimeOffset]::FromUnixTimeMilliseconds($klines[$_.entry_i].t).UtcDateTime
    $h = $dt.Hour
    if ($h -ge 13 -and $h -lt 17) { 'OVERLAP' }
    elseif ($h -ge 8 -and $h -lt 16) { 'LONDON' }
    elseif ($h -ge 13 -and $h -lt 21) { 'NEWYORK' }
    else { 'ASIAN' }
}
foreach ($grp in $sessionStats) {
    $wr = ($grp.Group | Where-Object { $_.pnl_usd -gt 0 }).Count / $grp.Count * 100
    $pnl = ($grp.Group | Measure-Object pnl_usd -Sum).Sum
    $pnlSign2 = if ($pnl -ge 0) { "+" } else { "" }
    Write-Host "    $($grp.Name.PadRight(10))  Trades: $($grp.Count.ToString().PadLeft(3))  WR: $($wr.ToString('F0').PadLeft(3))%  PnL: `$$pnlSign2$($pnl.ToString('F2'))"
}

Write-Host ""
Write-Host $sep -ForegroundColor Cyan

# Guardar JSON
$outPath = "$PSScriptRoot\backtest_results_v61.json"
$jsonOut = @{
    timestamp = (Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
    period    = "$startDate → $endDate"
    config    = $CFG
    results   = @{
        roi_pct=$roi; total_pnl=$totalPnL; final_equity=$finalEq
        win_rate=$winRate; max_drawdown=$maxDD
        profit_factor=$pf; rr_ratio=$rrRatio
        total_trades=$total; tp2_count=$tp2s.Count; sl_count=$sls.Count
        timeout_count=$touts.Count; long_count=$longs.Count; short_count=$shrts.Count
        avg_hold_candles=$avgHold
    }
    trades = ($trades | Select-Object entry_date, exit_date, direction, outcome, pnl_pts, pnl_usd, equity, hold_candles, score)
} | ConvertTo-Json -Depth 5

$jsonOut | Out-File -FilePath $outPath -Encoding UTF8
Write-Host "`n[✓] Resultados guardados en: $outPath" -ForegroundColor Green
