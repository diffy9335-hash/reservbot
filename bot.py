# ============================================================
# АДМИН-ПАНЕЛЬ
# ============================================================

@dp.callback_query(F.data == "admin_panel")
async def admin_panel_handler(callback: CallbackQuery, state: FSMContext):
    if not callback.from_user.username or callback.from_user.username.replace("@", "") not in ADMINS:
        return await callback.answer("У вас нет доступа к этой панели.", show_alert=True)

    text = (
        "👑 **Админ-панель**\n\n"
        "Отправьте мне **ID пользователя** (например `123456_1`) для управления:"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Отмена", callback_data="back_to_menu")]
    ])
    if callback.message.photo:
        await callback.message.delete()
        await callback.message.answer(text, parse_mode="Markdown", reply_markup=kb)
    else:
        try:
            await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=kb)
        except TelegramBadRequest:
            await callback.message.answer(text, parse_mode="Markdown", reply_markup=kb)
    await state.set_state(AdminPanel.waiting_for_user_id)


@dp.message(AdminPanel.waiting_for_user_id)
async def admin_user_management(message: Message, state: FSMContext):
    target_input = message.text.strip()
    players = await load_data(PLAYERS_FILE)

    if target_input in players and not players[target_input].get("retired"):
        target_id = target_input
    else:
        found = [uid for uid, p in players.items()
                 if uid.startswith(target_input + "_") and not p.get("retired")]

        if not found:
            return await message.answer(
                "❌ Активный игрок с таким ID не найден.\n"
                "Попробуй скопировать полный ID из профиля (например: `123456789_1`)",
                reply_markup=await main_menu_keyboard(message.from_user.username, await get_uid(message)),
                parse_mode="Markdown"
            )

        if len(found) > 1:
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(
                    text=f"Слот {uid.split('_')[1]}: {players[uid]['name']} ({players[uid].get('rating', 40)})",
                    callback_data=f"admin_select:{uid}"
                )] for uid in found
            ])
            await message.answer("Найдено несколько профилей. Выбери нужный:", reply_markup=kb)
            return

        target_id = found[0]

    await show_admin_user_profile(message, target_id)
    await state.clear()


@dp.callback_query(F.data.startswith("admin_select:"))
async def admin_select_handler(callback: CallbackQuery, state: FSMContext):
    target_id = callback.data.split(":")[1]
    await show_admin_user_profile(callback, target_id)
    await state.clear()


async def show_admin_user_profile(message_or_call, target_id):
    players = await load_data(PLAYERS_FILE)
    p = players[target_id]
    val = calculate_player_value(p["rating"], p["division"])

    parts = target_id.split("_")
    tg_id = parts[0]
    slot = parts[1] if len(parts) > 1 else "?"

    if p["position"] == "GK":
        stats_text = f"🧤 Сейвы: {p['stats_season'].get('saves', 0)}"
    elif p["position"] == "CB":
        stats_text = f"🛡️ Отборы: {p['stats_season'].get('tackles', 0)} | ⚽ Голы: {p['stats_season'].get('goals', 0)}"
    else:
        stats_text = f"⚽ Голы: {p['stats_season'].get('goals', 0)} | 🅰️ Ассисты: {p['stats_season'].get('assists', 0)}"

    text = (
        f"👑 ПРОФИЛЬ ИГРОКА\n━━━━━━━━━━━━━━━━━━━━\n"
        f"📱 Telegram ID: `{tg_id}`\n"
        f"💾 Полный ID: `{target_id}`\n"
        f"📁 Слот: {slot}\n"
        f"🏃‍♂️ {p['name']} | 🌍 {p.get('nation', 'Россия')} | 🎂 {p.get('age', 17)} лет\n"
        f"⚡️ Рейтинг: {p['rating']}/100\n"
        f"🏢 Клуб: {p['club']} ({p['position']})\n"
        f"💵 Баланс: {p.get('money', 0)}$ | 🏷️ Стоимость: {val:,}$\n"
        f"🏟️ Сезон: {p['season']} | Тур: {p['tour']}/30\n"
        f"🌍 Еврокубки: {get_euro_name(p.get('euro_tournament', 'none'))}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n{stats_text}"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏭ Тур (+1)", callback_data=f"adm_tour:{target_id}"),
         InlineKeyboardButton(text="⏭ Сезон (+1)", callback_data=f"adm_season:{target_id}")],
        [InlineKeyboardButton(text="💰 Выдать деньги", callback_data=f"adm_money:{target_id}"),
         InlineKeyboardButton(text="⚡️ Выдать рейтинг", callback_data=f"adm_rating:{target_id}")],
        [InlineKeyboardButton(text="🔙 В меню", callback_data="back_to_menu")]
    ])

    if isinstance(message_or_call, Message):
        await message_or_call.answer(text, reply_markup=kb, parse_mode="Markdown")
    else:
        try:
            await message_or_call.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")
        except TelegramBadRequest:
            pass


@dp.callback_query(F.data.startswith("adm_tour:"))
async def adm_skip_tour(callback: CallbackQuery):
    if not callback.from_user.username or callback.from_user.username.replace("@", "") not in ADMINS:
        return await callback.answer("Ошибка доступа.", show_alert=True)
    target_id = callback.data.split(":")[1]
    async with get_user_lock(target_id):
        players = await load_data(PLAYERS_FILE)
        if target_id in players:
            p = players[target_id]
            p["tour"] += 1
            p["money"] = p.get("money", 0) + p.get("contract_salary", 1500)
            p["train_done"] = False

            played_rivals = p.get("played_league_rivals", [])
            rival_pool = [c for c in CLUBS[p["division"]] if c != p["club"] and c not in played_rivals]
            if not rival_pool:
                rival_pool = [c for c in CLUBS[p["division"]] if c != p["club"]]
                p["played_league_rivals"] = []

            rival = random.choice(rival_pool)
            p["played_league_rivals"].append(rival)
            outcome = random.choice(["win", "draw", "loss"])

            p["stats_season"]["games"] += 1
            p["stats_total"]["games"] = p["stats_total"].get("games", 0) + 1

            if p["position"] in ["ST", "CM"]:
                goals = random.randint(0, 2) if outcome != "loss" else 0
                assists = random.randint(0, 1) if outcome != "loss" else 0
                p["stats_season"]["goals"] = p["stats_season"].get("goals", 0) + goals
                p["stats_season"]["assists"] = p["stats_season"].get("assists", 0) + assists
                p["stats_total"]["goals"] = p["stats_total"].get("goals", 0) + goals
                p["stats_total"]["assists"] = p["stats_total"].get("assists", 0) + assists
            elif p["position"] == "CB":
                tackles = random.randint(1, 5)
                goals = random.randint(0, 1) if outcome == "win" else 0
                p["stats_season"]["tackles"] = p["stats_season"].get("tackles", 0) + tackles
                p["stats_season"]["goals"] = p["stats_season"].get("goals", 0) + goals
                p["stats_total"]["tackles"] = p["stats_total"].get("tackles", 0) + tackles
                p["stats_total"]["goals"] = p["stats_total"].get("goals", 0) + goals
            elif p["position"] == "GK":
                saves = random.randint(1, 7)
                p["stats_season"]["saves"] = p["stats_season"].get("saves", 0) + saves
                p["stats_total"]["saves"] = p["stats_total"].get("saves", 0) + saves

            players[target_id] = p
            await save_data(PLAYERS_FILE, players)
            await simulate_table_tour(target_id, p["division"], p["club"], rival, outcome)

            await show_admin_user_profile(callback, target_id)


@dp.callback_query(F.data.startswith("adm_season:"))
async def adm_skip_season(callback: CallbackQuery):
    if not callback.from_user.username or callback.from_user.username.replace("@", "") not in ADMINS:
        return await callback.answer("Ошибка доступа.", show_alert=True)
    target_id = callback.data.split(":")[1]
    async with get_user_lock(target_id):
        players = await load_data(PLAYERS_FILE)
        if target_id in players:
            p = players[target_id]

            await generate_euro_data(p.get("season", 1) + 1)

            p["season"] += 1
            p["tour"] = 1

            for k in ["round_16_played", "playoff_round_played", "quarter_played", "semi_played", "final_played"]:
                p.pop(k, None)
            p["euro_playoff_stage"] = None
            p["stats_season"] = {"games": 0, "goals": 0, "assists": 0, "saves": 0, "tackles": 0}
            p["played_league_rivals"] = []
            p["fatigue"] = max(0, p.get("fatigue", 0) - 30)

            euro_data = await load_data(EURO_FILE)
            if euro_data and euro_data.get("status") == "group":
                tournament = None
                for t in ["champions_league", "europa_league", "conference_league"]:
                    if p["club"] in euro_data[t]["clubs"]:
                        tournament = t
                        break
                if tournament:
                    p["euro_tournament"] = tournament
                    p["euro_playoff_stage"] = None
                    p["euro_goals"] = 0
                    p["euro_assists"] = 0
                    p["euro_matches"] = 0
                else:
                    p["euro_tournament"] = "none"

            await init_tables_for_user(target_id, p["division"], p["club"])

            players[target_id] = p
            await save_data(PLAYERS_FILE, players)

            await show_admin_user_profile(callback, target_id)


@dp.callback_query(F.data.startswith("adm_money:"))
async def adm_money_btn(callback: CallbackQuery, state: FSMContext):
    target_id = callback.data.split(":")[1]
    await state.update_data(adm_target_id=target_id)
    await callback.message.edit_text("💰 Введите сумму долларов для выдачи:", parse_mode="Markdown")
    await state.set_state(AdminPanel.waiting_for_money)


@dp.message(AdminPanel.waiting_for_money)
async def adm_process_money(message: Message, state: FSMContext):
    data = await state.get_data()
    target_id = data.get("adm_target_id")
    try:
        amount = int(message.text.strip())
    except Exception:
        return await message.answer("❌ Число!")
    async with get_user_lock(target_id):
        players = await load_data(PLAYERS_FILE)
        if target_id in players:
            players[target_id]["money"] = players[target_id].get("money", 0) + amount
            await save_data(PLAYERS_FILE, players)
            await show_admin_user_profile(message, target_id)
    await state.clear()


@dp.callback_query(F.data.startswith("adm_rating:"))
async def adm_rating_btn(callback: CallbackQuery, state: FSMContext):
    target_id = callback.data.split(":")[1]
    await state.update_data(adm_target_id=target_id)
    await callback.message.edit_text("⚡️ Введите новый РЕЙТИНГ (1-100):", parse_mode="Markdown")
    await state.set_state(AdminPanel.waiting_for_rating)


@dp.message(AdminPanel.waiting_for_rating)
async def adm_process_rating(message: Message, state: FSMContext):
    data = await state.get_data()
    target_id = data.get("adm_target_id")
    try:
        rating = float(message.text.strip())
    except Exception:
        return await message.answer("❌ Число!")
    async with get_user_lock(target_id):
        players = await load_data(PLAYERS_FILE)
        if target_id in players:
            players[target_id]["rating"] = rating
            await save_data(PLAYERS_FILE, players)
            await show_admin_user_profile(message, target_id)
    await state.clear()


# ============================================================
# START И СОЗДАНИЕ ПЕРСОНАЖА
# ============================================================

@dp.message(F.text == "/start")
async def start_cmd(message: Message, state: FSMContext):
    await state.clear()

    if not await check_sub(message.from_user.id):
        return await message.answer(
            "❗️ **Для игры необходимо подписаться на нашего спонсора!**\nСначала подпишитесь, а затем нажмите кнопку проверки.",
            reply_markup=sub_keyboard(), parse_mode="Markdown"
        )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📁 Слот 1", callback_data="select_slot:1"),
         InlineKeyboardButton(text="📁 Слот 2", callback_data="select_slot:2")]
    ])
    await message.answer("⚽ **Добро пожаловать в симулятор футболиста!**\nВыбери слот для игры:",
                         reply_markup=kb, parse_mode="Markdown")


@dp.callback_query(F.data == "check_sub_callback")
async def check_sub_handler(callback: CallbackQuery, state: FSMContext):
    if not await check_sub(callback.from_user.id):
        return await callback.answer("❌ Вы не подписались! Подпишитесь и попробуйте снова.", show_alert=True)

    await callback.message.delete()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📁 Слот 1", callback_data="select_slot:1"),
         InlineKeyboardButton(text="📁 Слот 2", callback_data="select_slot:2")]
    ])
    await callback.message.answer("✅ Подписка подтверждена!\n\n⚽ **Добро пожаловать в симулятор футболиста!**\nВыбери слот для игры:",
                                  reply_markup=kb, parse_mode="Markdown")


@dp.callback_query(F.data.startswith("select_slot:"))
async def select_slot_handler(callback: CallbackQuery, state: FSMContext):
    slot = callback.data.split(":")[1]
    tg_id = str(callback.from_user.id)
    await set_active_slot(tg_id, slot)

    user_id = f"{tg_id}_{slot}"
    players = await load_data(PLAYERS_FILE)

    if user_id in players and not players[user_id].get("retired", False):
        players[user_id]["username_tg"] = callback.from_user.username
        await save_data(PLAYERS_FILE, players)
        await callback.message.edit_text(
            f"👋 **С возвращением, {players[user_id]['name']}!** (Слот {slot})\nТвой ID: `{user_id}`",
            reply_markup=await main_menu_keyboard(callback.from_user.username, user_id),
            parse_mode="Markdown"
        )
    else:
        if user_id in players and players[user_id].get("retired", False):
            history = players[user_id].get("career_history", [])
            await state.update_data(career_history=history)
            await callback.message.edit_text(
                f"⚽ **Твоя прошлая карьера (Слот {slot}) окончена. Начнем новую!**\nДля начала введи Имя и Фамилию:",
                parse_mode="Markdown"
            )
        else:
            await callback.message.edit_text(
                f"⚽ **Создаем профиль в Слоте {slot}!**\nДля начала введи Имя и Фамилию:",
                parse_mode="Markdown"
            )
        await state.set_state(PlayerCreation.waiting_for_name)


@dp.message(PlayerCreation.waiting_for_name)
async def process_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=NATIONS[i], callback_data=f"nat:{NATIONS[i]}"),
         InlineKeyboardButton(
             text=NATIONS[i + 1] if i + 1 < len(NATIONS) else NATIONS[i],
             callback_data=f"nat:{NATIONS[i + 1] if i + 1 < len(NATIONS) else NATIONS[i]}"
         )]
        for i in range(0, min(len(NATIONS), 32), 2)
    ])
    await message.answer("🌍 **Выбери свою национальность:**",
                         reply_markup=kb, parse_mode="Markdown")
    await state.set_state(PlayerCreation.waiting_for_nation)


@dp.callback_query(PlayerCreation.waiting_for_nation, F.data.startswith("nat:"))
async def process_nation(callback: CallbackQuery, state: FSMContext):
    await state.update_data(nation=callback.data.split(":")[1])
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=pos, callback_data=f"pos:{POSITIONS[pos]}")]
        for pos in POSITIONS.keys()
    ])
    await callback.message.edit_text("📋 **Выбери амплуа:**", reply_markup=kb, parse_mode="Markdown")
    await state.set_state(PlayerCreation.waiting_for_position)


@dp.callback_query(PlayerCreation.waiting_for_position, F.data.startswith("pos:"))
async def process_position(callback: CallbackQuery, state: FSMContext):
    await state.update_data(position=callback.data.split(":")[1])
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🇷🇺 Россия", callback_data="league:Россия"),
         InlineKeyboardButton(text="🇫🇷 Франция", callback_data="league:Франция")],
        [InlineKeyboardButton(text="🏴󠁧󠁢󠁥󠁮󠁧󠁿 Англия", callback_data="league:Англия"),
         InlineKeyboardButton(text="🇪🇸 Испания", callback_data="league:Испания")],
        [InlineKeyboardButton(text="🇮🇹 Италия", callback_data="league:Италия"),
         InlineKeyboardButton(text="🇩🇪 Германия", callback_data="league:Германия")],
        [InlineKeyboardButton(text="🇵🇹 Португалия", callback_data="league:Португалия"),
         InlineKeyboardButton(text="🇳🇱 Нидерланды", callback_data="league:Нидерланды")],
        [InlineKeyboardButton(text="🇧🇪 Бельгия", callback_data="league:Бельгия"),
         InlineKeyboardButton(text="🇧🇾 Беларусь", callback_data="league:Беларусь")],
        [InlineKeyboardButton(text="🇹🇷 Турция", callback_data="league:Турция")],
        [InlineKeyboardButton(text="🇰🇿 Казахстан", callback_data="league:Казахстан")]
    ])
    await callback.message.edit_text("🌍 **В какой стране начнешь карьеру?**",
                                     reply_markup=kb, parse_mode="Markdown")
    await state.set_state(PlayerCreation.waiting_for_country_league)


@dp.callback_query(PlayerCreation.waiting_for_country_league, F.data.startswith("league:"))
async def process_country_league(callback: CallbackQuery, state: FSMContext):
    league_country = callback.data.split(":")[1]
    mapping = {
        "Россия": "ФНЛ 2", "Франция": "Насьональ", "Англия": "Первая лига Англии",
        "Испания": "Сегунда", "Германия": "Вторая Бундеслига", "Италия": "Серия Б",
        "Португалия": "Сегунда лига", "Нидерланды": "Эрстедивизи",
        "Бельгия": "Jupiler Pro League", "Беларусь": "Беларусь Первая лига",
        "Турция": "Турция Первая лига", "Казахстан": "Казахстан Премьер-лига"
    }
    div = mapping.get(league_country, "ФНЛ 2")

    await state.update_data(start_division=div)
    await callback.message.edit_text("🔢 **Введи номер (1 - 99):**", parse_mode="Markdown")
    await state.set_state(PlayerCreation.waiting_for_number)


@dp.message(PlayerCreation.waiting_for_number)
async def process_number(message: Message, state: FSMContext):
    if not message.text.isdigit() or not (1 <= int(message.text) <= 99):
        return await message.answer("🚫 Выбери номер от 1 до 99:")

    await state.update_data(number=int(message.text))
    user_data = await state.get_data()
    start_div = user_data["start_division"]

    available_clubs = random.sample(CLUBS[start_div], 3)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🏢 {club}", callback_data=f"club:{club}")]
        for club in available_clubs
    ])
    await message.answer(f"📉 Тобой интересуются клубы из лиги: **{start_div}**. Где начнешь?",
                         reply_markup=kb, parse_mode="Markdown")
    await state.set_state(PlayerCreation.waiting_for_club)


@dp.callback_query(PlayerCreation.waiting_for_club, F.data.startswith("club:"))
@with_user_lock
async def process_club(callback: CallbackQuery, state: FSMContext):
    user_data = await state.get_data()
    user_id = await get_uid(callback)
    chosen_club = callback.data.split(":")[1]

    player_profile = {
        "name": user_data["name"],
        "nation": user_data.get("nation", "Россия"),
        "position": user_data["position"],
        "number": user_data["number"],
        "club": chosen_club,
        "division": get_division(chosen_club),
        "rating": 40.0,
        "trust": 15,
        "fatigue": 0,
        "girlfriend": "Нет",
        "age": 17,
        "season": 1,
        "tour": 1,
        "money": 5000,
        "contract_salary": 1500,
        "sponsor": None,
        "on_loan": False,
        "parent_club": None,
        "loan_tours_left": 0,
        "cup_out": False,
        "cup_stage": "1/16",
        "cup_rivals": [],
        "played_league_rivals": [],
        "trophies": [],
        "stats_season": {"games": 0, "goals": 0, "assists": 0, "saves": 0, "tackles": 0},
        "stats_total": {"games": 0, "goals": 0, "assists": 0, "saves": 0, "tackles": 0},
        "completed_quests": [],
        "train_done": False,
        "train_streak": 0,
        "train_count": 0,
        "train_tech_count": 0,
        "train_phys_count": 0,
        "train_special_count": 0,
        "train_achievements": [],
        "is_injured": False,
        "injury_tours": 0,
        "username_tg": callback.from_user.username,
        "career_history": user_data.get("career_history", []),
        "retired": False,
        "activity_minutes": 0,
        "activity_week": datetime.now().isocalendar()[1],
        "reputation": 50,
        "motivation": 50,
        "married": False,
        "children": 0,
        "wife_loyalty": 0,
        "business": None,
        "business_crisis": False,
        "business_crisis_timer": 0,
        "car": None,
        "has_yoga_bonus": False,
        "last_interview_tour": 0,
        "rating_performance": 0,
        "age_penalty_applied": False,
        "euro_tournament": None,
        "euro_goals": 0,
        "euro_assists": 0,
        "euro_matches": 0,
        "euro_playoff_stage": None,
        "national_call": None,
        "in_national_squad": False,
        "national_squad": None,
    }

    players = await load_data(PLAYERS_FILE)
    players[user_id] = player_profile
    await save_data(PLAYERS_FILE, players)
    await init_tables_for_user(user_id, player_profile["division"], player_profile["club"])

    await state.clear()
    await callback.message.edit_text(
        f"✍️ **КОНТРАКТ ПОДПИСАН!** Добро пожаловать в {player_profile['club']}!\n"
        f"💰 Твоя зарплата: {player_profile['contract_salary']}$ за матч.",
        parse_mode="Markdown",
        reply_markup=await main_menu_keyboard(callback.from_user.username, user_id)
    )


@dp.callback_query(F.data == "start_new_career")
@with_user_lock
async def start_new_career_handler(callback: CallbackQuery, state: FSMContext):
    await state.clear()

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📁 Слот 1", callback_data="select_slot:1"),
         InlineKeyboardButton(text="📁 Слот 2", callback_data="select_slot:2")]
    ])

    if callback.message.photo:
        await callback.message.delete()
        await callback.message.answer(
            "⚽ **Добро пожаловать в симулятор футболиста!**\nВыбери слот для игры:",
            reply_markup=kb, parse_mode="Markdown"
        )
    else:
        try:
            await callback.message.edit_text(
                "⚽ **Добро пожаловать в симулятор футболиста!**\nВыбери слот для игры:",
                reply_markup=kb, parse_mode="Markdown"
            )
        except Exception:
            await callback.message.answer(
                "⚽ **Добро пожаловать в симулятор футболиста!**\nВыбери слот для игры:",
                reply_markup=kb, parse_mode="Markdown"
            )


@dp.callback_query(F.data == "delete_career")
@with_user_lock
async def delete_career_confirm(callback: CallbackQuery):
    user_id = await get_uid(callback)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, удалить", callback_data="delete_career_yes")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="back_to_menu")]
    ])
    await callback.message.edit_text(
        "🗑 **Вы уверены, что хотите удалить свою карьеру?**\nЭто действие необратимо!",
        parse_mode="Markdown", reply_markup=kb
    )


@dp.callback_query(F.data == "delete_career_yes")
@with_user_lock
async def delete_career_final(callback: CallbackQuery, state: FSMContext):
    players = await load_data(PLAYERS_FILE)
    user_id = await get_uid(callback)
    if user_id in players:
        del players[user_id]
        await save_data(PLAYERS_FILE, players)

    await state.clear()

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📁 Слот 1", callback_data="select_slot:1"),
         InlineKeyboardButton(text="📁 Слот 2", callback_data="select_slot:2")]
    ])
    await callback.message.edit_text(
        "🗑 **Карьера удалена!**\n\n⚽ **Выбери слот для новой игры:**",
        reply_markup=kb, parse_mode="Markdown"
    )


# ============================================================
# ТРЕНИРОВКИ
# ============================================================

@dp.callback_query(F.data == "menu_train_choice")
@with_user_lock
async def train_choice_handler(callback: CallbackQuery):
    user_id = await get_uid(callback)
    await track_activity(user_id)
    p = (await load_data(PLAYERS_FILE)).get(user_id)
    if await deny_if_retired_cb(callback, p):
        return

    if p.get("injury_tours", 0) > 0:
        return await callback.answer(f"🚑 Вы травмированы! Осталось лечиться туров: {p['injury_tours']}.", show_alert=True)

    if p.get("train_done", False):
        return await callback.answer("🚫 Сыграй матч, чтобы открыть тренировку.", show_alert=True)

    fatigue = p.get("fatigue", 0)
    if fatigue >= 70:
        return await callback.answer(
            f"🚫 Ты слишком устал! Усталость: {fatigue}%\nСходи в ресторан или отдохни в личной жизни!",
            show_alert=True
        )

    cost = get_train_cost(p.get("rating", 40))
    if p.get("money", 0) < cost:
        return await callback.answer(f"❌ Не хватает денег! Нужно {cost}$, у тебя {p.get('money', 0)}$", show_alert=True)

    position = p.get("position", "ST")
    config = TRAINING_CONFIG.get(position, TRAINING_CONFIG["ST"])

    streak = p.get("train_streak", 0)
    streak_bonus = get_streak_bonus(streak)
    train_count = p.get("train_count", 0)

    fatigue_status = "✅ (можно тренироваться)" if fatigue < 70 else "❌ (отдохни!)"

    text = (
        f"🏋️‍♂️ **ТРЕНИРОВКА**\n━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 Рейтинг: **{p['rating']}**\n"
        f"🔋 Усталость: **{fatigue}%** {fatigue_status}\n"
        f"🔥 Серия: **{streak}** тренировок подряд\n"
        f"💪 Бонус за серию: **+{streak_bonus}**\n"
        f"💰 Стоимость: **{cost}$**\n"
        f"📈 Всего тренировок: **{train_count}**\n\n"
        f"**Выбери направление:**"
    )

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🎯 {config['tech']['name']}", callback_data="train:tech")],
        [InlineKeyboardButton(text=f"🏃 {config['phys']['name']}", callback_data="train:phys")],
        [InlineKeyboardButton(text=f"⭐ {config['special']['name']}", callback_data="train:special")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")]
    ])

    if callback.message.photo:
        await callback.message.delete()
        await callback.message.answer(text, reply_markup=kb, parse_mode="Markdown")
    else:
        await callback.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")


@dp.callback_query(F.data.startswith("train:"))
@with_user_lock
async def train_execute_handler(callback: CallbackQuery):
    user_id = await get_uid(callback)
    players = await load_data(PLAYERS_FILE)
    p = players.get(user_id)
    if await deny_if_retired_cb(callback, p):
        return

    train_type = callback.data.split(":")[1]

    if p.get("injury_tours", 0) > 0:
        return await callback.answer("🚑 Вы травмированы! Тренировка недоступна.", show_alert=True)

    if p.get("train_done", False):
        return await callback.answer("🚫 Сыграй матч, чтобы открыть тренировку.", show_alert=True)

    fatigue = p.get("fatigue", 0)
    if fatigue >= 70:
        return await callback.answer(f"🚫 Ты слишком устал! Усталость: {fatigue}%", show_alert=True)

    cost = get_train_cost(p.get("rating", 40))
    if p.get("money", 0) < cost:
        return await callback.answer(f"❌ Не хватает денег! Нужно {cost}$", show_alert=True)

    position = p.get("position", "ST")
    config = TRAINING_CONFIG.get(position, TRAINING_CONFIG["ST"])
    train_data = config.get(train_type, config["tech"])

    gain = train_data["base_gain"]

    streak = p.get("train_streak", 0)
    streak_bonus = get_streak_bonus(streak)
    total_gain = gain + streak_bonus

    golden = random.random() < 0.05
    if golden:
        total_gain *= 2

    failed = False
    if random.random() < 0.03:
        total_gain = -0.2
        failed = True

    inspiration = random.random() < 0.08

    injury_chance = 0.02 + (fatigue / 100) * 0.05
    injured = False
    injury_tours = 0

    if random.random() < injury_chance:
        injured = True
        injury_tours = random.randint(1, 3)
        p["injury_tours"] = injury_tours
        p["is_injured"] = True
        total_gain -= 0.5

    p["train_done"] = True
    p["fatigue"] = min(100, p.get("fatigue", 0) + train_data["fatigue"])
    p["money"] -= cost
    p["train_streak"] = streak + 1
    p["train_count"] = p.get("train_count", 0) + 1
    p["trust"] = min(100, p.get("trust", 15) + 3)

    p[f"train_{train_type}_count"] = p.get(f"train_{train_type}_count", 0) + 1

    if inspiration:
        p["fatigue"] = max(0, p["fatigue"] - 5)

    p["rating"] = max(1.0, min(100.0, round(p["rating"] + total_gain, 1)))

    new_achievements, ach_reward = check_train_achievements(
        p, p.get("train_count", 0), p.get("train_streak", 0)
    )

    if new_achievements:
        p["rating"] += ach_reward
        train_achievements = p.get("train_achievements", [])
        for ach in new_achievements:
            for key, val in TRAIN_ACHIEVEMENTS.items():
                if val["name"] == ach["name"] and key not in train_achievements:
                    train_achievements.append(key)
                    break
        p["train_achievements"] = train_achievements

    p["reputation"] = min(100, p.get("reputation", 50) + 0.5)

    players[user_id] = p
    await save_data(PLAYERS_FILE, players)
    await callback.message.delete()

    msg_lines = ["💪 **ТРЕНИРОВКА ЗАВЕРШЕНА!**", "━━━━━━━━━━━━━━━━━━━━"]
    msg_lines.append(f"📋 Направление: **{train_data['name']}**")

    if failed:
        msg_lines.append("😞 **ПРОВАЛ!** Рейтинг -0.2")
    elif injured:
        msg_lines.append(f"🚑 **ТРАВМА!** Выбытие на {injury_tours} тур(а)")
        msg_lines.append("📉 Рейтинг: -0.5 (штраф за травму)")
    else:
        msg_lines.append(f"📈 Прирост: +{gain}")
        if streak_bonus > 0:
            msg_lines.append(f"🔥 Бонус серии ({streak}): +{streak_bonus}")
        if golden:
            msg_lines.append("🌟 **ЗОЛОТАЯ ТРЕНИРОВКА! x2**")
        if inspiration:
            msg_lines.append("💡 Вдохновение! Усталость -5%")

    msg_lines.append("━━━━━━━━━━━━━━━━━━━━")
    msg_lines.append(f"⚡ Рейтинг: **{p['rating']}**")
    msg_lines.append(f"❤️ Доверие: **{p['trust']}**")
    msg_lines.append(f"🔋 Усталость: **{p['fatigue']}%**")
    msg_lines.append(f"💰 Потрачено: **{cost}$**")
    msg_lines.append(f"💵 Баланс: **{p['money']}$**")
    msg_lines.append("━━━━━━━━━━━━━━━━━━━━")
    msg_lines.append(f"🔥 Серия: **{p['train_streak']}** тренировок подряд")

    if new_achievements:
        msg_lines.append("━━━━━━━━━━━━━━━━━━━━")
        msg_lines.append("🎉 **НОВЫЕ ДОСТИЖЕНИЯ!**")
        for ach in new_achievements:
            msg_lines.append(f"🏅 {ach['name']} (+{ach['reward']})")

    if injured:
        msg_lines.append("\n⏳ Ты пропустишь матчи до восстановления!")

    await callback.message.answer(
        text="\n".join(msg_lines),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🏠 Меню", callback_data="back_to_menu")]
        ])
    )


@dp.callback_query(F.data == "back_to_menu")
async def back_to_menu_handler(callback: CallbackQuery):
    user_id = await get_uid(callback)
    if callback.message.photo:
        await callback.message.delete()
        await callback.message.answer("🏠 Главное меню.",
                                      reply_markup=await main_menu_keyboard(callback.from_user.username, user_id))
    else:
        try:
            await callback.message.edit_text("🏠 Главное меню.",
                                             reply_markup=await main_menu_keyboard(callback.from_user.username, user_id))
        except Exception:
            await callback.message.answer("🏠 Главное меню.",
                                          reply_markup=await main_menu_keyboard(callback.from_user.username, user_id))


@dp.callback_query(F.data == "menu_table")
@with_user_lock
async def show_table_handler(callback: CallbackQuery):
    user_id = await get_uid(callback)
    await track_activity(user_id)
    tables = await load_data(TABLES_FILE)
    p = (await load_data(PLAYERS_FILE)).get(user_id)
    if await deny_if_retired_cb(callback, p):
        return

    if user_id not in tables or p["division"] not in tables[user_id]:
        await init_tables_for_user(user_id, p["division"], p["club"])
        tables = await load_data(TABLES_FILE)

    table_data = tables[user_id][p["division"]]

    text = f"📊 **ТАБЛИЦА: {p['division']}**\n🏆 *Победа — 3 очка, Ничья — 1 очко, Поражение — 0*\n━━━━━━━━━━━━━━━━━━━━\n"
    for i, row in enumerate(table_data, 1):
        is_p = "👉 " if row["club"] == p["club"] else "• "
        text += f"{i}. {is_p}**{row['club']}** — {row['points']} очков ({row['wins']}В / {row['draws']}Н / {row['losses']}П)\n"

    if callback.message.photo:
        await callback.message.delete()
        await callback.message.answer(text, parse_mode="Markdown",
                                      reply_markup=await main_menu_keyboard(callback.from_user.username, user_id))
    else:
        try:
            await callback.message.edit_text(text, parse_mode="Markdown",
                                             reply_markup=await main_menu_keyboard(callback.from_user.username, user_id))
        except Exception:
            await callback.message.answer(text, parse_mode="Markdown",
                                          reply_markup=await main_menu_keyboard(callback.from_user.username, user_id))


@dp.callback_query(F.data == "menu_profile")
@with_user_lock
async def profile_handler(callback: CallbackQuery):
    user_id = await get_uid(callback)
    await track_activity(user_id)
    p = (await load_data(PLAYERS_FILE)).get(user_id)
    if not p:
        await callback.message.answer("⚠️ Профиль не найден. Нажми /start, чтобы начать.", parse_mode="Markdown")
        return

    if p.get("retired"):
        history_str = "\n\n".join(p.get("career_history", [])) or "—"
        text = (
            f"🏁 **КАРЬЕРА ЗАВЕРШЕНА**\n━━━━━━━━━━━━━━━━━━━━\n"
            f"🏃‍♂️ {p['name']} | 🌍 {p.get('nation', 'Россия')}\n\n"
            f"📚 **Завершенные карьеры (Статистика):**\n{history_str}\n\n"
            f"Нажми кнопку ниже, чтобы начать новую историю."
        )
        if callback.message.photo:
            await callback.message.delete()
            await callback.message.answer(text, parse_mode="Markdown", reply_markup=retired_keyboard())
        else:
            try:
                await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=retired_keyboard())
            except Exception:
                await callback.message.answer(text, parse_mode="Markdown", reply_markup=retired_keyboard())
        return

    val = calculate_player_value(p["rating"], p["division"])

    loan_status = f"\n⚠️ *В аренде из {p['parent_club']}* (Осталось: {p['loan_tours_left']} тур.)" if p.get("on_loan") else ""
    injury_status = f"\n🚑 *Травмирован!* (Лечиться еще: {p.get('injury_tours', 0)} тур.)" if p.get("injury_tours", 0) > 0 else ""

    if p["position"] == "GK":
        stats_text = f"🧤 Сейвы: {p['stats_season'].get('saves', 0)}"
    elif p["position"] == "CB":
        stats_text = f"🛡️ Отборы: {p['stats_season'].get('tackles', 0)} | ⚽ Голы: {p['stats_season'].get('goals', 0)}"
    else:
        stats_text = f"⚽ Голы: {p['stats_season'].get('goals', 0)} | 🅰️ Ассисты: {p['stats_season'].get('assists', 0)}"

    history_str = ""
    if p.get("career_history"):
        history_str = "\n\n📚 **Прошлые карьеры:**\n" + "\n\n".join(p["career_history"])

    season_display = min(p['season'], 13)
    tour_display = min(p['tour'], 30)

    kb = await main_menu_keyboard(callback.from_user.username, user_id)
    kb.inline_keyboard.append([InlineKeyboardButton(text="🗑 Удалить карьеру", callback_data="delete_career")])

    train_stats = (
        f"\n📊 **Тренировки:**\n"
        f"🔥 Серия: {p.get('train_streak', 0)}\n"
        f"📈 Всего: {p.get('train_count', 0)}\n"
        f"🎯 Техника: {p.get('train_tech_count', 0)} раз\n"
        f"🏃 Физика: {p.get('train_phys_count', 0)} раз\n"
        f"⭐ Специальная: {p.get('train_special_count', 0)} раз\n"
        f"🏅 Достижений: {len(p.get('train_achievements', []))}"
    )

    euro_stats = ""
    if p.get("euro_tournament") and p.get("euro_tournament") != "none":
        euro_stats = (
            f"\n🌍 **Еврокубки:** {get_euro_name(p['euro_tournament'])}\n"
            f"📈 Матчей: {p.get('euro_matches', 0)} | ⚽ Голов: {p.get('euro_goals', 0)} | 🅰️ Ассистов: {p.get('euro_assists', 0)}"
        )

    national_stats = ""
    if p.get("in_national_squad"):
        national_stats = f"\n🏆 **Сборная:** {p.get('nation', 'Россия')}"

    text = (
        f"👑 ПРОФИЛЬ ИГРОКА\n━━━━━━━━━━━━━━━━━━━━\n"
        f"🏃‍♂️ {p['name']} | 🌍 {p.get('nation', 'Россия')} | 🎂 {p.get('age', 17)} лет\n"
        f"⚡️ Рейтинг: {p['rating']}/100\n"
        f"🏢 Клуб: {p['club']} ({p['position']}){loan_status}{injury_status}\n"
        f"💵 Баланс: {p.get('money', 0)}$ | 🏷️ Стоимость: {val:,}$\n"
        f"🤝 Зарплата: {p.get('contract_salary', 0)}$/матч\n"
        f"💎 Спонсор: {p.get('sponsor', 'Нет')}\n"
        f"📊 Статус: {get_status_by_trust(p['trust'])}\n"
        f"🔋 Усталость: {p.get('fatigue', 0)}%\n"
        f"💍 Девушка: {p.get('girlfriend', 'Нет')}\n"
        f"🏟️ Сезон: {season_display}/13 | Тур Лиги: {tour_display}/30\n━━━━━━━━━━━━━━━━━━━━\n"
        f"🏆 **Текущая карьера (за сезон):**\n{stats_text}\n"
        f"📈 **Общая статистика (текущий игрок):**\nВсего игр: {p.get('stats_total', {}).get('games', 0)} | Голов: {p.get('stats_total', {}).get('goals', 0)} | Ассистов: {p.get('stats_total', {}).get('assists', 0)}"
        f"{euro_stats}{national_stats}{train_stats}{history_str}"
    )
    if callback.message.photo:
        await callback.message.delete()
        await callback.message.answer(text, reply_markup=kb)
    else:
        try:
            await callback.message.edit_text(text, reply_markup=kb)
        except Exception:
            await callback.message.answer(text, reply_markup=kb)


# ============================================================
# ОСНОВНОЙ МАТЧ ЛИГИ
# ============================================================

@dp.callback_query(F.data.startswith("scandal_club:"))
@with_user_lock
async def scandal_club_choice_handler(callback: CallbackQuery):
    user_id = await get_uid(callback)
    players = await load_data(PLAYERS_FILE)
    p = players.get(user_id)
    if await deny_if_retired_cb(callback, p):
        return
    new_club = callback.data.split(":")[1]

    p["club"] = new_club
    p["division"] = get_division(new_club)
    p["trust"] = 15

    base_salaries = {
        "ФНЛ 2": 1500, "Насьональ": 1500, "Первая лига Англии": 1800,
        "ФНЛ": 6000, "Лига 2": 6000, "Чемпионшип": 8000, "Сегунда": 8000, "Серия Б": 8000, "Вторая Бундеслига": 7500,
        "РПЛ": 30000, "Лига 1": 30000, "АПЛ": 50000, "Ла Лига": 50000, "Серия А": 45000, "Бундеслига": 48000,
        "Примейра": 35000, "Сегунда лига": 7500,
        "Бразильская Серия А": 30000,
        "Эрстедивизи": 7500, "Эредивизи": 35000,
        "Jupiler Pro League": 35000,
        "Беларусь Первая лига": 2000,
        "Беларусь Высшая лига": 5000,
        "Турция Первая лига": 3000,
        "Турция Суперлига": 25000,
        "Казахстан Премьер-лига": 25000
    }
    p["contract_salary"] = int(base_salaries.get(p["division"], 1500) * (p["rating"] / 45))
    p["played_league_rivals"] = []

    players[user_id] = p
    await save_data(PLAYERS_FILE, players)

    if p.get("tour", 1) <= 1:
        await init_tables_for_user(user_id, p["division"], p["club"])
    else:
        await simulate_table_until_tour(user_id, p["division"], p["club"], p["tour"])

    euro_data = await load_data(EURO_FILE)
    if euro_data and euro_data.get("status") == "group":
        tournament = None
        for t in ["champions_league", "europa_league", "conference_league"]:
            if p["club"] in euro_data[t]["clubs"]:
                tournament = t
                break
        p["euro_tournament"] = tournament if tournament else "none"

    players[user_id] = p
    await save_data(PLAYERS_FILE, players)

    await callback.message.delete()
    await callback.message.answer(
        text=f"✍️ Ты успешно перешел в **{new_club}**!\n"
             f"💵 Твоя новая зарплата: **{p['contract_salary']}$/матч**.\n"
             f"📊 Таблица для новой лиги создана!\n"
             f"Пора доказывать фанатам свою преданность!",
        parse_mode="Markdown",
        reply_markup=await main_menu_keyboard(callback.from_user.username, user_id)
    )


@dp.callback_query(F.data == "menu_match")
@with_user_lock
async def match_handler(callback: CallbackQuery, state: FSMContext):
    if not await check_sub(callback.from_user.id):
        return await callback.message.answer(
            "❗️ **Для игры необходимо подписаться на нашего спонсора!**\nСначала подпишитесь, а затем продолжите игру.",
            reply_markup=sub_keyboard(), parse_mode="Markdown"
        )

    user_id = await get_uid(callback)
    await heal_injury_if_needed(user_id)
    await track_activity(user_id)
    players = await load_data(PLAYERS_FILE)
    p = players.get(user_id)
    if await deny_if_retired_cb(callback, p):
        return

    if not p.get("train_done", False):
        if p.get("train_streak", 0) > 0:
            p["train_streak"] = 0
            players[user_id] = p
            await save_data(PLAYERS_FILE, players)
            await send_auto_delete_message(
                callback.message,
                "⚠️ **СЕРИЯ ПРЕРВАНА!**\nТы сыграл матч, но не потренировался.\n🔥 Серия тренировок сброшена до 0!",
                delay=3
            )

    trust = p.get("trust", 15)
    status = get_status_by_trust(trust)

    if trust < 21:
        p["tour"] += 1
        p["money"] = p.get("money", 0) + p.get("contract_salary", 1500)
        p["train_done"] = False
        p["fatigue"] = max(0, p.get("fatigue", 0) - 10)

        played_rivals = p.get("played_league_rivals", [])
        rival_pool = [c for c in CLUBS[p["division"]] if c != p["club"] and c not in played_rivals]
        if not rival_pool:
            rival_pool = [c for c in CLUBS[p["division"]] if c != p["club"]]
            p["played_league_rivals"] = []

        rival = random.choice(rival_pool)
        p["played_league_rivals"].append(rival)
        outcome = random.choice(["win", "draw", "loss"])
        p["stats_season"]["games"] += 1

        players[user_id] = p
        await save_data(PLAYERS_FILE, players)
        await simulate_table_tour(user_id, p["division"], p["club"], rival, outcome)

        if callback.message.photo:
            await callback.message.delete()

        await send_auto_delete_message(
            callback.message,
            f"🪑 **ТЫ В РЕЗЕРВЕ!**\nТы не попал в состав на матч против **{rival}**.\n"
            f"📊 Статус: {status}\n💡 Подними доверие (trust) до 21, чтобы играть!\n"
            f"🔹 Итог матча: **{'Победа' if outcome == 'win' else 'Ничья' if outcome == 'draw' else 'Поражение'}**",
            delay=3
        )
        return

    if p.get("injury_tours", 0) > 0:
        p["tour"] += 1
        p["money"] = p.get("money", 0) + p.get("contract_salary", 1500)
        p["train_done"] = False
        p["fatigue"] = max(0, p.get("fatigue", 0) - 10)

        played_rivals = p.get("played_league_rivals", [])
        rival_pool = [c for c in CLUBS[p["division"]] if c != p["club"] and c not in played_rivals]
        if not rival_pool:
            rival_pool = [c for c in CLUBS[p["division"]] if c != p["club"]]
            p["played_league_rivals"] = []

        rival = random.choice(rival_pool)
        p["played_league_rivals"].append(rival)
        outcome = random.choice(["win", "draw", "loss"])
        p["stats_season"]["games"] += 1

        players[user_id] = p
        await save_data(PLAYERS_FILE, players)
        await simulate_table_tour(user_id, p["division"], p["club"], rival, outcome)

        if callback.message.photo:
            await callback.message.delete()

        msg = (f"🚑 **ТЫ ПРОПУСТИЛ ТУР ИЗ-ЗА ТРАВМЫ**\n"
               f"Команда сыграла против **{rival}**. Итог: "
               f"**{'Победа' if outcome == 'win' else 'Ничья' if outcome == 'draw' else 'Поражение'}**.\n")
        if p["injury_tours"] > 0:
            msg += f"⏳ Осталось лечиться: {p['injury_tours']} тур(а)."
        else:
            msg += "✅ **Ты полностью восстановился и готов к следующему матчу!**"

        await send_auto_delete_message(callback.message, msg, delay=3)
        return

    if p.get("fatigue", 0) >= 95:
        return await callback.answer("🚫 Ты смертельно устал! Сходи в ресторан.", show_alert=True)

    current_rating = p.get("rating", 40)

    if trust < 51:
        total_moments = random.randint(1, 2)
        await send_auto_delete_message(
            callback.message,
            f"🔄 **ТЫ НА ЗАМЕНЕ!**\nТы выйдешь на поле во втором тайме.\n"
            f"📊 Статус: {status}\n💡 Играй лучше, чтобы попасть в старт!",
            delay=3
        )
    else:
        total_moments = random.randint(2, 4)

    offer_made = False
    if not offer_made and p["division"] not in ["Бундеслига", "Вторая Бундеслига"] and random.random() < 0.10:
        if current_rating >= 74:
            ger_offers = random.sample(CLUBS["Бундеслига"], 2)
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=f"🇩🇪 {c}", callback_data=f"scandal_club:{c}")] for c in ger_offers
            ] + [[InlineKeyboardButton(text="❌ Отклонить предложение", callback_data="back_to_menu")]])
            await callback.message.delete()
            return await callback.message.answer(
                text=f"📈 **ТРАНСФЕРНОЕ ПРЕДЛОЖЕНИЕ!** Твой высокий рейтинг ({current_rating}) привлек внимание клубов из Германии! Тебе предлагают контракт в **Бундеслиге**:",
                reply_markup=kb, parse_mode="Markdown"
            )
        elif current_rating >= 55:
            ger_offers = random.sample(CLUBS["Вторая Бундеслига"], 2)
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=f"🇩🇪 {c}", callback_data=f"scandal_club:{c}")] for c in ger_offers
            ] + [[InlineKeyboardButton(text="❌ Отклонить предложение", callback_data="back_to_menu")]])
            await callback.message.delete()
            return await callback.message.answer(
                text=f"📈 **ТРАНСФЕРНОЕ ПРЕДЛОЖЕНИЕ!** На основе твоего рейтинга ({current_rating}) команды из Германии предлагают тебе контракт во **Второй Бундеслиге**:",
                reply_markup=kb, parse_mode="Markdown"
            )

    if not offer_made and p["division"] not in ["Примейра", "Сегунда лига"] and random.random() < 0.10:
        if current_rating >= 74:
            pt_offers = random.sample(CLUBS["Примейра"], 2)
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=f"🇵🇹 {c}", callback_data=f"scandal_club:{c}")] for c in pt_offers
            ] + [[InlineKeyboardButton(text="❌ Отклонить предложение", callback_data="back_to_menu")]])
            await callback.message.delete()
            return await callback.message.answer(
                text=f"📈 **ТРАНСФЕРНОЕ ПРЕДЛОЖЕНИЕ!** Твой высокий рейтинг ({current_rating}) привлек внимание клубов из Португалии! Тебе предлагают контракт в **Примейре**:",
                reply_markup=kb, parse_mode="Markdown"
            )
        elif current_rating >= 55:
            pt_offers = random.sample(CLUBS["Сегунда лига"], 2)
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=f"🇵🇹 {c}", callback_data=f"scandal_club:{c}")] for c in pt_offers
            ] + [[InlineKeyboardButton(text="❌ Отклонить предложение", callback_data="back_to_menu")]])
            await callback.message.delete()
            return await callback.message.answer(
                text=f"📈 **ТРАНСФЕРНОЕ ПРЕДЛОЖЕНИЕ!** На основе твоего рейтинга ({current_rating}) команды из Португалии предлагают тебе контракт в **Сегунда лиге**:",
                reply_markup=kb, parse_mode="Markdown"
            )

    if p["tour"] > 30:
        return await season_results_handler(callback)

    if random.random() < 0.01:
        div_clubs = [c for c in CLUBS[p["division"]] if c != p["club"]]
        available_clubs = random.sample(div_clubs, min(len(div_clubs), 2))

        top_leagues = ["РПЛ", "Лига 1", "АПЛ", "Ла Лига", "Серия А", "Бундеслига", "Примейра",
                       "Бразильская Серия А", "Эредивизи", "Jupiler Pro League",
                       "Беларусь Высшая лига", "Турция Суперлига", "Казахстан Премьер-лига"]
        my_top_league = "РПЛ"
        if p["division"] in ["Насьональ", "Лига 2", "Лига 1"]: my_top_league = "Лига 1"
        elif p["division"] in ["Первая лига Англии", "Чемпионшип", "АПЛ"]: my_top_league = "АПЛ"
        elif p["division"] in ["Сегунда", "Ла Лига"]: my_top_league = "Ла Лига"
        elif p["division"] in ["Серия Б", "Серия А"]: my_top_league = "Серия А"
        elif p["division"] in ["Вторая Бундеслига", "Бундеслига"]: my_top_league = "Бундеслига"
        elif p["division"] in ["Сегунда лига", "Примейра"]: my_top_league = "Примейра"
        elif p["division"] in ["Бразильская Серия А"]: my_top_league = "Бразильская Серия А"
        elif p["division"] in ["Эрстедивизи", "Эредивизи"]: my_top_league = "Эредивизи"
        elif p["division"] in ["Jupiler Pro League"]: my_top_league = "Jupiler Pro League"
        elif p["division"] in ["Беларусь Первая лига", "Беларусь Высшая лига"]: my_top_league = "Беларусь Высшая лига"
        elif p["division"] in ["Турция Первая лига", "Турция Суперлига"]: my_top_league = "Турция Суперлига"
        elif p["division"] in ["Казахстан Премьер-лига"]: my_top_league = "Казахстан Премьер-лига"

        alt_leagues = [l for l in top_leagues if l != my_top_league]
        alt_league = random.choice(alt_leagues) if alt_leagues else "РПЛ"
        available_clubs.append(random.choice(CLUBS[alt_league]))
        random.shuffle(available_clubs)

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"🏢 {club}", callback_data=f"scandal_club:{club}")]
            for club in available_clubs
        ])
        await callback.message.delete()
        return await callback.message.answer(
            text=f"🤬 **СКАНДАЛ С РУКОВОДСТВОМ!** Твой контракт с {p['club']} разорван.\n"
                 f"Интерес к тебе проявили клубы. Выбери новую команду:",
            reply_markup=kb, parse_mode="Markdown"
        )

    p["stats_season"]["games"] += 1
    p["fatigue"] = min(100, p.get("fatigue", 0) + 15)

    cup_stg = p.get("cup_stage", "1/16")
    is_cup_match = (not p.get("cup_out", False)) and (cup_stg in CUP_STAGES) and random.random() < 0.20

    if is_cup_match:
        country_leagues = []
        if p["division"] in ["ФНЛ 2", "ФНЛ", "РПЛ"]: country_leagues = ["ФНЛ 2", "ФНЛ", "РПЛ"]
        elif p["division"] in ["Насьональ", "Лига 2", "Лига 1"]: country_leagues = ["Насьональ", "Лига 2", "Лига 1"]
        elif p["division"] in ["Первая лига Англии", "Чемпионшип", "АПЛ"]: country_leagues = ["Первая лига Англии", "Чемпионшип", "АПЛ"]
        elif p["division"] in ["Сегунда", "Ла Лига"]: country_leagues = ["Сегунда", "Ла Лига"]
        elif p["division"] in ["Серия Б", "Серия А"]: country_leagues = ["Серия Б", "Серия А"]
        elif p["division"] in ["Вторая Бундеслига", "Бундеслига"]: country_leagues = ["Вторая Бундеслига", "Бундеслига"]
        elif p["division"] in ["Сегунда лига", "Примейра"]: country_leagues = ["Сегунда лига", "Примейра"]
        elif p["division"] in ["Бразильская Серия А"]: country_leagues = ["Бразильская Серия А"]
        elif p["division"] in ["Эрстедивизи", "Эредивизи"]: country_leagues = ["Эрстедивизи", "Эредивизи"]
        elif p["division"] in ["Jupiler Pro League"]: country_leagues = ["Jupiler Pro League"]
        elif p["division"] in ["Беларусь Первая лига", "Беларусь Высшая лига"]: country_leagues = ["Беларусь Первая лига", "Беларусь Высшая лига"]
        elif p["division"] in ["Турция Первая лига", "Турция Суперлига"]: country_leagues = ["Турция Первая лига", "Турция Суперлига"]
        elif p["division"] in ["Казахстан Премьер-лига"]: country_leagues = ["Казахстан Премьер-лига"]

        rival_pool = []
        for l in country_leagues:
            rival_pool.extend(CLUBS[l])
        played_cup_rivals = p.get("cup_rivals", [])
        rival_pool = [c for c in rival_pool if c != p["club"] and c not in played_cup_rivals]
        if not rival_pool:
            rival_pool = ["Случайная команда"]
    else:
        played_rivals = p.get("played_league_rivals", [])
        rival_pool = [c for c in CLUBS[p["division"]] if c != p["club"] and c not in played_rivals]
        if not rival_pool:
            rival_pool = [c for c in CLUBS[p["division"]] if c != p["club"]]
            p["played_league_rivals"] = []
        players[user_id] = p
        await save_data(PLAYERS_FILE, players)

    match_data = {
        "rival": random.choice(rival_pool),
        "total_moments": total_moments,
        "current_moment": 1,
        "minute": 0, "goals": 0, "assists": 0, "saves": 0, "tackles": 0, "yellow_cards": 0,
        "my_team_score": 0, "rival_team_score": 0,
        "is_cup": is_cup_match, "cup_stage": cup_stg if is_cup_match else None,
        "log": ""
    }
    await state.update_data(match=match_data)

    match_title = f"🏆 НАЦИОНАЛЬНЫЙ КУБОК ({cup_stg}) 🏆" if is_cup_match else f"🏟️ РЕГУЛЯРНЫЙ ЧЕМПИОНАТ ({p['division']})"

    if callback.message.photo:
        await callback.message.delete()
    msg = await callback.message.answer(
        f"⚽ **{match_title}**\n⚔️ **{p['club']}** vs **{match_data['rival']}**\nСудья дает свисток к началу игры!",
        parse_mode="Markdown"
    )
    await asyncio.sleep(2)
    await msg.delete()
    await generate_moment(callback, state, user_id)


async def generate_moment(callback: CallbackQuery, state: FSMContext, user_id: str):
    data = await state.get_data()
    if "match" not in data:
        return
    m = data["match"]
    p = (await load_data(PLAYERS_FILE)).get(user_id)

    m["minute"] += random.randint(15, 25)
    if m["minute"] > 90:
        m["minute"] = 90

    my_rating = CLUB_RATINGS.get(p["club"], 50)
    rival_rating = CLUB_RATINGS.get(m["rival"], 50)
    rating_diff = my_rating - rival_rating

    if random.random() < 0.65:
        if random.random() < 0.5:
            rival_score_chance = 0.40 - (rating_diff * 0.02)
            if random.random() < max(0.05, min(0.95, rival_score_chance)):
                m["rival_team_score"] += 1
                m["log"] += f"⚡ **{m['minute']}'** | ГОЛ! Соперник забивает мяч в ваши ворота.\n"
        else:
            team_score_chance = 0.40 + (rating_diff * 0.02)
            if random.random() < max(0.05, min(0.95, team_score_chance)):
                m["my_team_score"] += 1
                m["log"] += f"⚽ **{m['minute']}'** | ГОЛ! Твоя команда забивает отличный гол!\n"

    if random.random() < 0.4:
        flavor = random.choice([
            "🔥 Красивый финт в центре поля обостряет игру.",
            "📐 Подача углового, но защита выносит мяч.",
            "🟨 Судья показывает желтую карточку игроку соперника.",
            "⚔️ Жесткий стык, но судья не дает свисток.",
            "👐 Вратарь уверенно забирает мяч после навеса."
        ])
        m["log"] += f"⏱ **{m['minute']}'** | {flavor}\n"

    if random.random() < 0.08:
        card_roll = random.random()
        if card_roll < 0.15:
            m["log"] += f"🟥 **{m['minute']}'** | ПРЯМАЯ КРАСНАЯ! Грубейший фол, ты удален с поля!\n"
            m["minute"] = 90
        else:
            m["log"] += f"🟨 **{m['minute']}'** | Судья показывает тебе желтую карточку за срыв атаки.\n"
            m["yellow_cards"] = m.get("yellow_cards", 0) + 1
            if m["yellow_cards"] >= 2:
                m["log"] += f"🟥 **{m['minute']}'** | ВТОРАЯ ЖЕЛТАЯ! ТЕБЯ УДАЛЯЮТ С ПОЛЯ!\n"
                m["minute"] = 90

    if m["current_moment"] > m["total_moments"] or m["minute"] == 90:
        is_knockout = m["is_cup"]
        if is_knockout and m["my_team_score"] == m["rival_team_score"]:
            await start_penalty_shootout(callback, state, user_id)
        else:
            await finish_match(callback, state, user_id)
        return

    text = (f"⏱ **{m['minute']}' МИНУТА** | Момент {m['current_moment']}/{m['total_moments']}\n"
            f"⚔️ **{p['club']}** vs **{m['rival']}**\n"
            f"Счет: **{m['my_team_score']} : {m['rival_team_score']}**\n\n"
            f"📝 **События матча:**\n{m['log'] or 'Идет плотная позиционная борьба...'}\n")

    m["log"] = ""

    if p["position"] == "GK":
        text += "🚨 **Опасность! Нападающий соперника выходит один на один с тобой! Твои действия?**"
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🧤 Прыгнуть в левый угол", callback_data="gk_act:left"),
             InlineKeyboardButton(text="🧤 Прыгнуть в правый угол", callback_data="gk_act:right")],
            [InlineKeyboardButton(text="🏃 Сблизить дистанцию", callback_data="gk_act:rush")]
        ])
    elif p["position"] == "CB":
        if random.random() < 0.75:
            text += "🛡️ **Форвард соперника идет на дриблинге прямо в твою зону!**"
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🧲 Жесткий подкат", callback_data="cb_act:tackle_hard"),
                 InlineKeyboardButton(text="🕴️ Встретить корпусом", callback_data="cb_act:tackle_smart")],
                [InlineKeyboardButton(text="📐 Отдать пас ближнему", callback_data="act:pass")]
            ])
        else:
            text += "🔥 **Ты подключился на угловой! Мяч летит к тебе!**"
            kb = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🎯 Пробить головой", callback_data="act:shoot_menu"),
                 InlineKeyboardButton(text="📐 Сбросить под удар партнеру", callback_data="act:pass")]
            ])
    else:
        text += "🔥 **Ты контролируешь мяч на подступах к штрафной! Твое решение?**"
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🎯 Пробить по воротам", callback_data="act:shoot_menu"),
             InlineKeyboardButton(text="📐 Отдать пас", callback_data="act:pass")]
        ])

    await state.update_data(match=m)
    try:
        await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=kb)
    except Exception:
        await callback.message.answer(text, parse_mode="Markdown", reply_markup=kb)


@dp.callback_query(F.data.startswith("gk_act:"))
@with_user_lock
async def gk_action_handler(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if "match" not in data:
        return await callback.answer("⏳ Матч уже завершен!", show_alert=True)
    m = data["match"]
    action = callback.data.split(":")[1]
    user_id = await get_uid(callback)
    p = (await load_data(PLAYERS_FILE)).get(user_id)

    rival_rating = CLUB_RATINGS.get(m["rival"], 50)
    save_chance = 0.30 + ((p["rating"] - rival_rating) * 0.015) + (p["rating"] * 0.004)
    save_chance = max(0.1, min(0.95, save_chance))

    opp_shoot_dir = random.choice(["left", "right", "center"])
    if action == "rush":
        is_saved = random.random() < (save_chance + 0.1)
    else:
        is_saved = (action == opp_shoot_dir) or (random.random() < save_chance * 0.8)

    if is_saved:
        m["saves"] += 1
        m["log"] += f"🧤 **{m['minute']}'** | БЕЗУМНЫЙ СЕЙВ! Ты вытаскиваешь мертвейший мяч!\n"
    else:
        m["rival_team_score"] += 1
        m["log"] += f"⚡ **{m['minute']}'** | Гол... Оппонент технично переиграл тебя на противоходе.\n"
    m["current_moment"] += 1
    await state.update_data(match=m)
    await generate_moment(callback, state, user_id)


@dp.callback_query(F.data.startswith("cb_act:"))
@with_user_lock
async def cb_action_handler(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if "match" not in data:
        return await callback.answer("⏳ Матч уже завершен!", show_alert=True)
    m = data["match"]
    action = callback.data.split(":")[1]
    user_id = await get_uid(callback)
    p = (await load_data(PLAYERS_FILE)).get(user_id)

    rival_rating = CLUB_RATINGS.get(m["rival"], 50)
    tackle_chance = 0.30 + ((p["rating"] - rival_rating) * 0.015) + (p["rating"] * 0.003)
    tackle_chance = max(0.1, min(0.90, tackle_chance))

    if action == "tackle_hard":
        if random.random() < 0.15:
            m["rival_team_score"] += 1
            m["log"] += f"⚡ **{m['minute']}'** | Фол в штрафной! Ты сфолил, соперник забивает пенальти.\n"
        elif random.random() < tackle_chance:
            m["tackles"] += 1
            m["log"] += f"🛡️ **{m['minute']}'** | Мощнейший чистый подкат! Форвард лежит, мяч отобран!\n"
        else:
            m["rival_team_score"] += 1
            m["log"] += f"⚡ **{m['minute']}'** | Ошибка! Нападающий пробросил мяч мимо тебя и забил.\n"
    else:
        if random.random() < tackle_chance:
            m["tackles"] += 1
            m["log"] += f"🛡️ **{m['minute']}'** | Отличный выбор позиции. Ты заблокировал продвижение соперника.\n"
        else:
            m["rival_team_score"] += 1
            m["log"] += f"⚡ **{m['minute']}'** | Тебя легко обыграли на замахе. Гол.\n"
    m["current_moment"] += 1
    await state.update_data(match=m)
    await generate_moment(callback, state, user_id)


@dp.callback_query(F.data == "act:shoot_menu")
@with_user_lock
async def act_shoot_menu_handler(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if "match" not in data:
        return await callback.answer("⏳ Матч уже завершен!", show_alert=True)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📐 Левый верхний (Девятка)", callback_data="shoot_dir:в левую девятку"),
         InlineKeyboardButton(text="📐 Правый верхний (Девятка)", callback_data="shoot_dir:в правую девятку")],
        [InlineKeyboardButton(text="👇 Левый нижний", callback_data="shoot_dir:низом в левый угол"),
         InlineKeyboardButton(text="👇 Правый нижний", callback_data="shoot_dir:низом в правый угол")]
    ])
    try:
        await callback.message.edit_reply_markup(reply_markup=kb)
    except Exception:
        pass


@dp.callback_query(F.data.startswith("shoot_dir:"))
@with_user_lock
async def act_shoot_execute_handler(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if "match" not in data:
        return await callback.answer("⏳ Матч уже завершен!", show_alert=True)
    m = data["match"]
    target_dir = callback.data.split(":")[1]
    user_id = await get_uid(callback)
    p = (await load_data(PLAYERS_FILE)).get(user_id)

    rival_rating = CLUB_RATINGS.get(m["rival"], 50)
    score_chance = 0.60 + ((p["rating"] - rival_rating) * 0.015)
    gk_dive = random.choice(["в левую девятку", "в правую девятку", "низом в левый угол", "низом в правый угол"])

    if gk_dive == target_dir:
        score_chance -= 0.15
        gk_guessed = True
    else:
        score_chance += 0.10
        gk_guessed = False
    score_chance = max(0.05, min(0.95, score_chance))

    if random.random() < score_chance:
        m["goals"] += 1
        m["my_team_score"] += 1
        try:
            await callback.message.edit_text(
                f"⚽ **{m['minute']}'** | ГОЛ! Твой шикарный удар {target_dir} разрывает сетку ворот!",
                parse_mode="Markdown"
            )
        except Exception:
            pass
        await asyncio.sleep(2)
        m["log"] += f"⚽ **{m['minute']}'** | ГОЛ! Твой шикарный удар {target_dir}!\n"
    else:
        if gk_guessed:
            m["log"] += f"❌ **{m['minute']}'** | Ты пробил {target_dir}, но голкипер парировал удар!\n"
        else:
            m["log"] += f"❌ **{m['minute']}'** | Целился {target_dir}, но мяч пролетел мимо!\n"
    m["current_moment"] += 1
    await state.update_data(match=m)
    await generate_moment(callback, state, user_id)


@dp.callback_query(F.data == "act:pass")
@with_user_lock
async def act_pass_handler(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if "match" not in data:
        return await callback.answer("⏳ Матч уже завершен!", show_alert=True)
    m = data["match"]
    user_id = await get_uid(callback)
    p = (await load_data(PLAYERS_FILE)).get(user_id)

    rival_rating = CLUB_RATINGS.get(m["rival"], 50)
    pass_chance = 0.60 + ((p["rating"] - rival_rating) * 0.015)
    pass_chance = max(0.05, min(0.95, pass_chance))

    if random.random() < pass_chance:
        m["assists"] += 1
        m["my_team_score"] += 1
        m["log"] += f"✅ **{m['minute']}'** | Шикарный точный пас на партнера, и он вколачивает мяч в сетку! ГОЛ!\n"
    else:
        m["log"] += f"❌ **{m['minute']}'** | Пас оказался неточным, перехват соперника.\n"
    m["current_moment"] += 1
    await state.update_data(match=m)
    await generate_moment(callback, state, user_id)


async def _clear_match_state(state: FSMContext):
    data = await state.get_data()
    data.pop("match", None)
    await state.set_data(data)


async def start_penalty_shootout(callback: CallbackQuery, state: FSMContext, user_id: str):
    data = await state.get_data()
    m = data.get("match")
    if not m:
        return await _clear_match_state(state)

    players = await load_data(PLAYERS_FILE)
    p = players.get(user_id)
    if not p:
        return await _clear_match_state(state)

    rival_rating = CLUB_RATINGS.get(m["rival"], 50)
    my_chance = 0.5 + ((p.get("rating", 40) - rival_rating) * 0.01)
    my_chance = max(0.25, min(0.75, my_chance))

    my_score, rival_score = 0, 0
    for _ in range(5):
        if random.random() < 0.75:
            my_score += 1
        if random.random() < 0.75:
            rival_score += 1
    while my_score == rival_score:
        if random.random() < my_chance:
            my_score += 1
        else:
            rival_score += 1

    won_shootout = my_score > rival_score
    m["log"] += f"\n🥅 **СЕРИЯ ПЕНАЛЬТИ:** {my_score} : {rival_score} — {'ТЫ ПРОШЕЛ ДАЛЬШЕ!' if won_shootout else 'вы вылетаете...'}\n"

    if won_shootout:
        m["my_team_score"] += 1
    else:
        m["rival_team_score"] += 1

    await state.update_data(match=m)
    await finish_match(callback, state, user_id, penalty_result=(my_score, rival_score, won_shootout))


async def finish_match(callback: CallbackQuery, state: FSMContext, user_id: str, penalty_result=None):
    data = await state.get_data()
    m = data.get("match")
    if not m:
        return await callback.message.answer(
            "⚠️ Данные матча были потеряны. Возвращаю в главное меню.",
            reply_markup=await main_menu_keyboard(callback.from_user.username, user_id)
        )

    players = await load_data(PLAYERS_FILE)
    p = players.get(user_id)
    if not p:
        await _clear_match_state(state)
        return

    if m["my_team_score"] > m["rival_team_score"]:
        outcome = "win"
        outcome_text = "🏆 **ПОБЕДА!**"
        p["trust"] = min(100, p.get("trust", 0) + 5)
    elif m["my_team_score"] == m["rival_team_score"]:
        outcome = "draw"
        outcome_text = "🤝 **НИЧЬЯ**"
        p["trust"] = min(100, p.get("trust", 0) + 1)
    else:
        outcome = "loss"
        outcome_text = "❌ **ПОРАЖЕНИЕ**"
        p["trust"] = max(0, p.get("trust", 0) - 4)

    p.setdefault("stats_season", {"games": 0, "goals": 0, "assists": 0, "saves": 0, "tackles": 0})
    p.setdefault("stats_total", {"games": 0, "goals": 0, "assists": 0, "saves": 0, "tackles": 0})
    for stat in ("goals", "assists", "saves", "tackles"):
        p["stats_season"][stat] = p["stats_season"].get(stat, 0) + m.get(stat, 0)
        p["stats_total"][stat] = p["stats_total"].get(stat, 0) + m.get(stat, 0)
    p["stats_total"]["games"] = p["stats_total"].get("games", 0) + 1

    goals = m.get("goals", 0)
    assists = m.get("assists", 0)
    saves = m.get("saves", 0)
    tackles = m.get("tackles", 0)
    conceded = m.get("rival_team_score", 0)

    raw = (goals * 0.35 + assists * 0.25 + saves * 0.25 + tackles * 0.15
           - conceded * 0.10
           + (0.20 if outcome == "win" else (-0.15 if outcome == "loss" else 0.0)))
    raw = max(-1.0, min(1.0, raw))
    rating_delta = round(raw * 0.06, 2)
    p["rating"] = round(max(1.0, min(100.0, p.get("rating", 40.0) + rating_delta)), 2)

    money_gain = p.get("contract_salary", 1500)
    sponsor_income = 0
    sp_name = p.get("sponsor")
    if sp_name and sp_name in SPONSORS_DATA:
        sponsor_income = SPONSORS_DATA[sp_name]["income_per_match"]
        money_gain += sponsor_income
    p["money"] = p.get("money", 0) + money_gain
    p["train_done"] = False

    cup_summary = ""
    if m.get("is_cup"):
        p["cup_rivals"] = p.get("cup_rivals", []) + [m["rival"]]
        if outcome == "win":
            stages = CUP_STAGES
            current_stage = m.get("cup_stage") or p.get("cup_stage", "1/16")
            idx = stages.index(current_stage) if current_stage in stages else -1
            if idx == len(stages) - 1:
                p["trophies"] = p.get("trophies", []) + [f"🏆 Кубок сезона {p.get('season', 1)}"]
                p["money"] += 100000
                p["rating"] = max(1.0, min(100.0, round(p["rating"] + 0.5, 1)))
                p["cup_out"] = True
                cup_summary = "\n\n🏆 **ТЫ ВЫИГРАЛ НАЦИОНАЛЬНЫЙ КУБОК!!!** 🎉"
            else:
                p["cup_stage"] = stages[idx + 1]
                cup_summary = f"\n\n➡️ Ты прошел в стадию **{p['cup_stage']}** Кубка!"
        else:
            p["cup_out"] = True
            cup_summary = "\n\n🚫 Твоя команда вылетела из Кубка на этой стадии."
    else:
        p["tour"] = p.get("tour", 1) + 1
        p["played_league_rivals"] = p.get("played_league_rivals", []) + [m["rival"]]
        await simulate_table_tour(user_id, p["division"], p["club"], m["rival"], outcome)
        if p.get("on_loan") and p.get("parent_club"):
            parent_div = get_division(p["parent_club"])
            if parent_div != p["division"]:
                await simulate_background_division(user_id, parent_div)

    age = p.get("age", 17)
    if age >= 36:
        p["rating"] = max(1.0, round(p["rating"] - 0.3, 1))
    elif age >= 33:
        p["rating"] = max(1.0, round(p["rating"] - 0.2, 1))
    elif age >= 30:
        p["rating"] = max(1.0, round(p["rating"] - 0.1, 1))

    players[user_id] = p
    await save_data(PLAYERS_FILE, players)
    await _clear_match_state(state)

    penalty_line = ""
    if penalty_result:
        my_pen, rival_pen, _ = penalty_result
        penalty_line = f"🥅 Пенальти: {my_pen} : {rival_pen}\n"

    sponsor_line = (f"💼 Доход от {p.get('sponsor')}: +{sponsor_income}$\n" if sponsor_income else "")

    rating_performance = 5.0
    rating_performance += goals * 1.0
    rating_performance += assists * 0.8
    rating_performance += saves * 0.5
    rating_performance += tackles * 0.5
    if outcome == "win":
        rating_performance += 1.0
    elif outcome == "draw":
        rating_performance += 0.5
    rating_performance -= conceded * 0.3
    rating_performance = max(5.0, min(10.0, rating_performance))
    rating_performance = round(rating_performance, 1)
    p["rating_performance"] = rating_performance

    text = (
        f"🏁 **МАТЧ ЗАВЕРШЕН!**\n"
        f"⚔️ **{p['club']} {m['my_team_score']} : {m['rival_team_score']} {m['rival']}**\n"
        f"{penalty_line}{outcome_text}\n\n"
        f"📊 **Оценка за матч: {rating_performance} / 10**\n"
        f"⚽ Голы: {m.get('goals', 0)} | 🅰️ Ассисты: {m.get('assists', 0)} | "
        f"🧤 Сейвы: {m.get('saves', 0)} | 🛡️ Отборы: {m.get('tackles', 0)}\n"
        f"💰 Зарплата: +{p.get('contract_salary', 1500)}$\n"
        f"{sponsor_line}"
        f"📈 Рейтинг: {p['rating']} ({'+' if rating_delta >= 0 else ''}{rating_delta})"
        f"{cup_summary}"
    )

    kb = await main_menu_keyboard(callback.from_user.username, user_id)
    try:
        await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=kb)
    except Exception:
        if callback.message.photo:
            await callback.message.delete()
        await callback.message.answer(text, parse_mode="Markdown", reply_markup=kb)

    if rating_performance >= 9.0:
        await start_interview(callback, state, user_id, p)


def _pick_offers_by_rating(rating: float, current_club: str, current_division: str) -> list:
    low = max(0, int(rating) - 15)
    high = min(100, int(rating) + 20)
    candidates = []
    for div, clubs in CLUBS.items():
        for club in clubs:
            cr = CLUB_RATINGS.get(club, 50)
            if low <= cr <= high and club != current_club:
                candidates.append({"club": club, "division": div, "club_rating": cr})
    if len(candidates) < 4:
        candidates = [
            {"club": c, "division": d, "club_rating": CLUB_RATINGS.get(c, 50)}
            for d, clubs in CLUBS.items()
            for c in clubs
            if c != current_club
        ]
    random.shuffle(candidates)
    seen_divs = set()
    offers = []
    for cand in candidates:
        if cand["division"] not in seen_divs:
            seen_divs.add(cand["division"])
            salary = max(1500, int(cand["club_rating"] * 150 + rating * 50))
            cand["salary"] = salary
            offers.append(cand)
        if len(offers) == 4:
            break
    if len(offers) < 4:
        used = {o["club"] for o in offers}
        for cand in candidates:
            if cand["club"] not in used:
                salary = max(1500, int(cand["club_rating"] * 150 + rating * 50))
                cand["salary"] = salary
                offers.append(cand)
                used.add(cand["club"])
            if len(offers) == 4:
                break
    return offers


async def start_interview(callback: CallbackQuery, state: FSMContext, user_id: str, p: dict):
    questions = [
        {
            "question": "Как ты оцениваешь свой вклад в сегодняшнюю победу?",
            "a": "Я был лидером и вёл команду за собой",
            "b": "Я просто выполнял свою работу на поле",
            "trust_a": 5, "trust_b": 2
        },
        {
            "question": "Что бы ты сказал болельщикам после такого матча?",
            "a": "Спасибо за вашу невероятную поддержку!",
            "b": "Мы ещё не всё показали, впереди много побед!",
            "trust_a": 3, "trust_b": 4
        },
        {
            "question": "Какой момент матча ты запомнил больше всего?",
            "a": "Мой забитый мяч / сейв / отбор",
            "b": "Командная работа и дух борьбы",
            "trust_a": 4, "trust_b": 3
        }
    ]
    await state.set_state(InterviewState.waiting_for_answer)
    await state.update_data(interview={"questions": questions, "trust_gain": 0})
    q0 = questions[0]
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=q0["a"], callback_data="interview:0:a")],
        [InlineKeyboardButton(text=q0["b"], callback_data="interview:0:b")]
    ])
    await callback.message.answer(
        f"🎙️ **Поздравляем с выдающимся матчем! Твоя оценка {p.get('rating_performance', 9.0)}!**\n"
        f"Журналисты хотят задать тебе несколько вопросов.\n\n"
        f"**Вопрос 1/3:**\n_{q0['question']}_",
        parse_mode="Markdown", reply_markup=kb
    )


@dp.callback_query(F.data.startswith("interview:"))
@with_user_lock
async def interview_handler(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split(":")
    if len(parts) != 3:
        return await callback.answer()
    q_idx = int(parts[1])
    choice = parts[2]

    data = await state.get_data()
    iv = data.get("interview")
    if not iv:
        await callback.answer()
        user_id = await get_uid(callback)
        kb = await main_menu_keyboard(callback.from_user.username, user_id)
        try:
            await callback.message.edit_reply_markup(reply_markup=kb)
        except Exception:
            pass
        return

    questions = iv["questions"]
    trust_gain = iv.get("trust_gain", 0)
    rep_gain = iv.get("rep_gain", 0)

    if q_idx < len(questions):
        q = questions[q_idx]
        if choice == "a":
            trust_gain += q.get("trust_a", 0)
            rep_gain += q.get("rep_a", 0)
        elif choice == "b":
            trust_gain += q.get("trust_b", 0)
            rep_gain += q.get("rep_b", 0)
        else:
            trust_gain += q.get("trust_c", 0)
            rep_gain += q.get("rep_c", 0)

    user_id = await get_uid(callback)
    next_idx = q_idx + 1

    await callback.answer()

    if next_idx < len(questions):
        await state.update_data(interview={
            "questions": questions,
            "current": next_idx,
            "trust_gain": trust_gain,
            "rep_gain": rep_gain
        })

        nq = questions[next_idx]
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"A) {nq['a']}", callback_data=f"interview:{next_idx}:a")],
            [InlineKeyboardButton(text=f"B) {nq['b']}", callback_data=f"interview:{next_idx}:b")]
        ])

        try:
            await callback.message.edit_text(
                f"🎙️ **Интервью — вопрос {next_idx + 1}/3:**\n_{nq['question']}_\n\nВыбери ответ:",
                parse_mode="Markdown", reply_markup=kb
            )
        except Exception as e:
            logging.warning(f"interview next_q error: {e}")
    else:
        await state.update_data(interview=None)
        players = await load_data(PLAYERS_FILE)
        p = players.get(user_id)
        if p:
            p["trust"] = min(100, p.get("trust", 0) + trust_gain)
            p["reputation"] = min(100, max(0, p.get("reputation", 50) + rep_gain))
            players[user_id] = p
            await save_data(PLAYERS_FILE, players)

        trust_now = p.get("trust", 0) if p else 0
        rep_now = p.get("reputation", 50) if p else 50
        text = (
            f"🎙️ **Интервью завершено!**\n"
            f"📣 Твои ответы произвели впечатление на публику!\n"
            f"❤️ +{trust_gain} к доверию болельщиков (итого: {trust_now})\n"
            f"⭐ {rep_gain:+} к репутации (итого: {rep_now})"
        )
        kb = await main_menu_keyboard(callback.from_user.username, user_id)
        try:
            await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=kb)
        except Exception as e:
            logging.warning(f"interview finish error: {e}")
            await callback.message.answer(text, parse_mode="Markdown", reply_markup=kb)


# ============================================================
# ИТОГИ СЕЗОНА
# ============================================================

async def season_results_handler(callback: CallbackQuery):
    user_id = await get_uid(callback)
    players = await load_data(PLAYERS_FILE)
    p = players.get(user_id)
    if await deny_if_retired_cb(callback, p):
        return

    async with get_table_lock():
        tables = await load_data(TABLES_FILE)
        table = tables.get(user_id, {}).get(p["division"], [])
    table_sorted = sorted(table, key=lambda x: x["points"], reverse=True)
    total_clubs = max(len(table_sorted), 1)
    position = next((i + 1 for i, row in enumerate(table_sorted) if row["club"] == p["club"]), total_clubs)

    season_num = p.get("season", 1)

    ladder = get_ladder(p["division"])
    idx_in_ladder = ladder.index(p["division"]) if p["division"] in ladder else 0

    promotion_div = None
    relegation_div = None

    if position == 1:
        result_text = f"🥇 **ЧЕМПИОНСТВО!** 1 место из {total_clubs} в **{p['division']}**!"
        p["trophies"] = p.get("trophies", []) + [f"🥇 Чемпион «{p['division']}» (Сезон {season_num})"]
        if idx_in_ladder < len(ladder) - 1:
            promotion_div = ladder[idx_in_ladder + 1]
            result_text += f"\n📈 Ваша команда получила путевку в **{promotion_div}**!"
    elif position <= 2 and idx_in_ladder < len(ladder) - 1:
        promotion_div = ladder[idx_in_ladder + 1]
        result_text = (f"🎉 **ВЫХОД В ВЫСШИЙ ДИВИЗИОН!** {position} место из {total_clubs}.\n"
                       f"Команда пробилась в **{promotion_div}**!")
        p["trophies"] = p.get("trophies", []) + [f"⬆️ Выход в «{promotion_div}» (Сезон {season_num})"]
    elif position >= total_clubs - 1 and total_clubs > 2 and idx_in_ladder > 0:
        relegation_div = ladder[idx_in_ladder - 1]
        result_text = (f"📉 **ВЫЛЕТ!** {position} место из {total_clubs}.\n"
                       f"Команда падает в **{relegation_div}**.")
    else:
        result_text = f"📊 {position} место из {total_clubs} в **{p['division']}**."

    stats = p.get("stats_season", {"games": 0, "goals": 0, "assists": 0, "saves": 0, "tackles": 0})
    pos_code = p.get("position", "ST")
    if pos_code == "GK":
        stats_text = f"🎮 {stats.get('games', 0)} матчей | 🧤 {stats.get('saves', 0)} сейвов"
    elif pos_code == "CB":
        stats_text = f"🎮 {stats.get('games', 0)} матчей | 🛡️ {stats.get('tackles', 0)} отборов | ⚽ {stats.get('goals', 0)} голов"
    else:
        stats_text = f"🎮 {stats.get('games', 0)} матчей | ⚽ {stats.get('goals', 0)} голов | 🅰️ {stats.get('assists', 0)} ассистов"

    p["age"] = p.get("age", 17) + 1
    retired_now = False

    if season_num > 13 or (p["age"] >= 36 and random.random() < 0.35):
        retired_now = True
        p["retired"] = True
        career_summary = (f"📌 {p['name']} | Рейтинг: {p['rating']} | "
                          f"Клуб: {p['club']} | Трофеев: {len(p.get('trophies', []))}")
        p["career_history"] = p.get("career_history", []) + [career_summary]
        await add_to_retired_leaderboard(p["name"], p["rating"], len(p.get("trophies", [])))

    if retired_now:
        awards = await calculate_player_awards(user_id, season_num)
        bonuses = await apply_awards_bonuses(user_id, awards, season_num)
        players = await load_data(PLAYERS_FILE)
        p = players.get(user_id)

        _apply_new_season_reset(p)
        players[user_id] = p
        await save_data(PLAYERS_FILE, players)

        awards_text = ""
        if awards:
            awards_text = "\n\n🏆 **НОМИНАЦИИ СЕЗОНА:**\n"
            if awards.get("golden_ball"):
                gb = awards["golden_ball"]
                mark = "⭐ " if gb.get("is_player") else ""
                awards_text += f"🥇 ЗМ: {mark}{gb['name']}\n"
            if awards.get("golden_glove"):
                gg = awards["golden_glove"]
                mark = "⭐ " if gg.get("is_player") else ""
                awards_text += f"🧤 ЗП: {mark}{gg['name']}\n"
            if awards.get("best_defender"):
                bd = awards["best_defender"]
                mark = "⭐ " if bd.get("is_player") else ""
                awards_text += f"🛡️ ЛЗ: {mark}{bd['name']}\n"
            if awards.get("best_assistant"):
                ba = awards["best_assistant"]
                mark = "⭐ " if ba.get("is_player") else ""
                awards_text += f"🅰️ ЛА: {mark}{ba['name']}\n"

        if bonuses:
            awards_text += "\n🎁 **ТВОИ НАГРАДЫ:**\n" + "\n".join(bonuses)

        text = (
            f"🏁 **ИТОГИ СЕЗОНА {season_num}**\n━━━━━━━━━━━━━━━━━━━━\n"
            f"{result_text}\n\n"
            f"📊 {stats_text}\n"
            f"{awards_text}\n\n"
            f"🏁 **Карьера завершена! Ты провел великий путь и уходишь на заслуженную пенсию.**"
        )
        try:
            await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=retired_keyboard())
        except Exception:
            if callback.message.photo:
                await callback.message.delete()
            await callback.message.answer(text, parse_mode="Markdown", reply_markup=retired_keyboard())
        return

    rating = p.get("rating", 40.0)
    offers = _pick_offers_by_rating(rating, p["club"], p["division"])

    forced_div = promotion_div or relegation_div
    if forced_div:
        forced_club = random.choice([c for c in CLUBS.get(forced_div, []) if c != p["club"]] or CLUBS.get(forced_div, [p["club"]]))
        forced_salary = max(1500, int(CLUB_RATINGS.get(forced_club, 50) * 150 + rating * 50))
        forced_offer = {"club": forced_club, "division": forced_div,
                        "club_rating": CLUB_RATINGS.get(forced_club, 50), "salary": forced_salary}
        offers = [o for o in offers if o["division"] != forced_div][:3]
        offers.insert(0, forced_offer)

    p["_season_offers"] = offers
    p["_season_num"] = season_num
    p["_season_forced_div"] = forced_div
    p["_season_result_text"] = result_text
    p["_season_stats_text"] = stats_text
    players[user_id] = p
    await save_data(PLAYERS_FILE, players)

    current_salary = p.get("contract_salary", 1500)
    renew_salary = max(current_salary, int(current_salary * 1.15))
    buttons = []
    for i, o in enumerate(offers):
        label = f"🏟 {o['club']} ({o['division']}) — {o['salary']}$/матч"
        buttons.append([InlineKeyboardButton(text=label, callback_data=f"season_choice:{i}")])
    buttons.append([InlineKeyboardButton(
        text=f"🔄 Продлить контракт с {p['club']} — {renew_salary}$/матч",
        callback_data="season_choice:renew"
    )])

    awards = await calculate_player_awards(user_id, season_num)
    bonuses = await apply_awards_bonuses(user_id, awards, season_num)

    players = await load_data(PLAYERS_FILE)
    p = players.get(user_id)

    awards_text = ""
    if awards:
        awards_text = "\n\n🏆 **НОМИНАЦИИ СЕЗОНА:**\n"
        if awards.get("golden_ball"):
            gb = awards["golden_ball"]
            mark = "⭐ " if gb.get("is_player") else ""
            awards_text += f"🥇 ЗМ: {mark}{gb['name']}\n"
        if awards.get("golden_glove"):
            gg = awards["golden_glove"]
            mark = "⭐ " if gg.get("is_player") else ""
            awards_text += f"🧤 ЗП: {mark}{gg['name']}\n"
        if awards.get("best_defender"):
            bd = awards["best_defender"]
            mark = "⭐ " if bd.get("is_player") else ""
            awards_text += f"🛡️ ЛЗ: {mark}{bd['name']}\n"
        if awards.get("best_assistant"):
            ba = awards["best_assistant"]
            mark = "⭐ " if ba.get("is_player") else ""
            awards_text += f"🅰️ ЛА: {mark}{ba['name']}\n"

    if bonuses:
        awards_text += "\n🎁 **ТВОИ НАГРАДЫ:**\n" + "\n".join(bonuses)

    buttons.append([InlineKeyboardButton(
        text="🏆 Подробнее о номинациях",
        callback_data="menu_awards"
    )])

    text = (
        f"🏁 **ИТОГИ СЕЗОНА {season_num}**\n━━━━━━━━━━━━━━━━━━━━\n"
        f"{result_text}\n\n"
        f"📊 {stats_text}\n"
        f"{awards_text}\n\n"
        f"📋 **Выбери, где продолжить карьеру:**"
    )

    try:
        if callback.message.photo:
            await callback.message.delete()
            await callback.message.answer(text, parse_mode="Markdown",
                                          reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
        else:
            await callback.message.edit_text(text, parse_mode="Markdown",
                                             reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    except Exception as e:
        logging.warning(f"season_results_handler send error: {e}")
        await callback.message.answer(text, parse_mode="Markdown",
                                      reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))


def _apply_new_season_reset(p: dict):
    p["season"] = p.get("_season_num", p.get("season", 1)) + 1
    p["tour"] = 1
    p["stats_season"] = {"games": 0, "goals": 0, "assists": 0, "saves": 0, "tackles": 0}
    p["played_league_rivals"] = []
    p["cup_out"] = False
    p["cup_stage"] = "1/16"
    p["cup_rivals"] = []
    p["train_done"] = False
    p["fatigue"] = max(0, p.get("fatigue", 0) - 30)
    for key in ("_season_offers", "_season_num", "_season_result_text", "_season_stats_text", "_season_forced_div"):
        p.pop(key, None)


@dp.callback_query(F.data.startswith("season_choice:"))
@with_user_lock
async def season_choice_handler(callback: CallbackQuery):
    user_id = await get_uid(callback)
    players = await load_data(PLAYERS_FILE)
    p = players.get(user_id)
    if not p:
        return await callback.answer("⚠️ Профиль не найден. Нажми /start.", show_alert=True)

    offers = p.get("_season_offers", [])
    choice = callback.data.split(":")[1]
    season_num = p.get("_season_num", p.get("season", 1))
    forced_div = p.get("_season_forced_div")

    if choice == "renew":
        old_salary = p.get("contract_salary", 1500)
        p["contract_salary"] = max(old_salary, int(old_salary * 1.15))

        if forced_div:
            p["division"] = forced_div
            club_line = (f"🔄 Ты продлил контракт с **{p['club']}**!\n"
                         f"📈 Твоя команда переходит в **{forced_div}**!\n"
                         f"💰 Новая зарплата: **{p['contract_salary']}$/матч**")
        else:
            club_line = (f"🔄 Ты продлил контракт с **{p['club']}**!\n"
                         f"💰 Новая зарплата: **{p['contract_salary']}$/матч**")
    else:
        try:
            idx = int(choice)
        except ValueError:
            return await callback.answer("❌ Неверный выбор.", show_alert=True)
        if idx < 0 or idx >= len(offers):
            return await callback.answer("❌ Предложение недоступно.", show_alert=True)
        offer = offers[idx]
        p["club"] = offer["club"]
        p["division"] = offer["division"]
        p["contract_salary"] = offer["salary"]
        p["trust"] = 15
        club_line = (f"✍️ Контракт подписан!\n"
                     f"🏟 Клуб: **{p['club']}** ({p['division']})\n"
                     f"💰 Зарплата: **{p['contract_salary']}$/матч**")

    new_season = p.get("season", 1) + 1
    await generate_euro_data(new_season)
    euro_data = await load_data(EURO_FILE)

    if euro_data and euro_data.get("status") == "group":
        tournament = None
        for t in ["champions_league", "europa_league", "conference_league"]:
            if p["club"] in euro_data[t]["clubs"]:
                tournament = t
                break

        if tournament:
            p["euro_tournament"] = tournament
            p["euro_goals"] = 0
            p["euro_assists"] = 0
            p["euro_matches"] = 0
            p["euro_playoff_stage"] = None
            club_line += f"\n\n🌍 {get_euro_name(tournament)}!"
        else:
            p["euro_tournament"] = "none"
    else:
        p["euro_tournament"] = "none"

    _apply_new_season_reset(p)
    players[user_id] = p
    await save_data(PLAYERS_FILE, players)
    await init_tables_for_user(user_id, p["division"], p["club"])

    # ✅ Проверка на ЧМ (каждый новый сезон)
    season = p.get("season", 1)
    tour_type, year = get_national_tournament_for_season(season)
    national_line = ""
    if tour_type:
        await init_national_tournament(tour_type)
        await notify_all_national_calls(tour_type)
        national_line = f"\n\n🏆 **{NATIONAL_TOURNAMENTS[tour_type]['name']} {year} начинается!**"
        if p.get("national_call") and p["national_call"].get("status") == "pending":
            national_line += "\n📨 У тебя вызов в сборную!"

    text = (
        f"🎉 **СЕЗОН {season_num} ЗАВЕРШЁН!**\n━━━━━━━━━━━━━━━━━━━━\n"
        f"{club_line}\n\n"
        f"➡️ Начинается **Сезон {p['season']}**!"
        f"{national_line}\n\n"
        f"Удачи!"
    )
    kb = await main_menu_keyboard(callback.from_user.username, user_id)
    try:
        await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=kb)
    except Exception as e:
        logging.warning(f"season_choice_handler edit error: {e}")
        if callback.message.photo:
            await callback.message.delete()
        await callback.message.answer(text, parse_mode="Markdown", reply_markup=kb)


# ============================================================
# ЗАПУСК
# ============================================================

async def ensure_files_exist():
    files_defaults = {
        PLAYERS_FILE: {},
        LEADERBOARD_FILE: {"top_careers": []},
        TABLES_FILE: {},
        SLOTS_FILE: {},
        EURO_FILE: {},
        AWARDS_FILE: {},
        NPC_FILE: {},
        NATIONAL_FILE: {},
    }
    for filename, default_value in files_defaults.items():
        if not os.path.exists(filename):
            await save_data(filename, default_value)
            print(f"📁 Создан файл: {filename}")


async def main():
    print("🚀 Бот запущен и ожидает сообщений...")
    print("📌 Еврокубки: 36 клубов, 8 туров (round-robin)")
    print("📌 Плей-офф: стыки + 1/8, 1/4, 1/2, Финал")
    print("📌 Сборные: 32 нации, ТОЛЬКО ЧМ")
    print("📌 Турниры сборных каждые 2 сезона")
    print("📌 Очки в группе: победа=3, ничья=1, поражение=0")
    print("📌 Авто-симуляция других групп")
    print("📌 Авто-создание плей-офф после 3 туров")
    print("📌 Матчи засчитываются корректно (фикс бага)")
    print("📌 1 момент = 1 момент (фикс двойного инкремента)")

    await ensure_files_exist()

    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
