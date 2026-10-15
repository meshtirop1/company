"""UI text for the cutting module, in English and Korean.

Each page has a single template shared by both languages; only these strings differ.
A test checks that the two dictionaries carry the same keys and the same placeholders,
so a string added in one language can't be forgotten in the other.

Placeholders: messages built in views use named `{fields}` filled by str.format.
The `err_max_length` string is filled by Django itself, so it uses `%(limit_value)d`.
"""


def get_lang(request):
    """The UI language chosen in the navbar switcher (stored in the session by set_language)."""
    return 'ko' if request.session.get('language') == 'ko' else 'en'


STRINGS = {
    'en': {
        'nav': 'Fish Cutting',
        'module': 'Fish cutting pay',
        'hub_intro': (
            "Records and prices the cutting crew's work. Cutters never log in — "
            'the supervisor enters everything here.'
        ),
        'home': '← Cutting home',
        'save': 'Save',
        'cancel': 'Cancel',
        'edit': 'Edit',
        'delete': 'Delete',
        'activate': 'Activate',
        'deactivate': 'Deactivate',

        'tile_cutters': 'Cutters',
        'tile_cutters_desc': 'The crew roster — add, rename or deactivate cutters.',
        'tile_prices': 'Price list',
        'tile_prices_desc': 'Per-box rates by style and size, each with a start date.',
        'stat_active_cutters': 'Active cutters',
        'stat_price_items': 'Priced sizes',

        'cutters_title': 'Cutters',
        'cutters_intro': (
            "Cutters are records only — they don't get a login. Deactivate someone who has left: "
            'they drop off the daily entry list, but their past work stays.'
        ),
        'add_cutter': 'Add a cutter',
        'edit_cutter': 'Edit cutter — {name}',
        'name': 'Name',
        'note': 'Note',
        'note_help': 'Optional — e.g. phone number or team.',
        'active_cutters': 'Active cutters',
        'inactive_cutters': 'Inactive cutters',
        'no_cutters': 'No cutters yet — add the first one above.',
        'cutter_added': 'Added {name}.',
        'cutter_saved': 'Saved {name}.',
        'cutter_activated': '{name} is active again.',
        'cutter_deactivated': '{name} is now inactive.',
        'cutter_deleted': 'Deleted {name}.',
        'cutter_in_use': "{name} has work records, so they can't be deleted. Deactivate them instead.",
        'confirm_delete_cutter': "Delete {name}? This can't be undone.",
        'err_duplicate_name': (
            'There is already a cutter with this name. Add something to tell them apart, e.g. "Kim (A)".'
        ),

        'prices_title': 'Price list',
        'prices_intro': (
            'Pay is per box. Each rate has a start date and applies from that day on. '
            'When a rate changes, work already recorded keeps the price it was saved with.'
        ),
        'style': 'Style',
        'size': 'Size',
        'size_help': 'As written on the price list — e.g. 7, 10~11, 4,5,6.',
        'sort_order': 'Display order',
        'sort_order_help': 'Smaller numbers show first. Leave blank to add it at the end.',
        'unit_price': 'Price per box (₩)',
        'effective_from': 'Starts on',
        'since': 'since {date}',
        'no_current_rate': 'No rate in force today',
        'upcoming_rate': 'From {date}: ₩{price}',
        'rate_history': 'Rate history',
        'add_rate': 'New rate',
        'add_rate_title': 'New rate — {item}',
        'edit_rate_title': 'Edit rate — {item}',
        'add_item': 'Add a size',
        'add_item_intro': 'Adds a new line to the price list together with its first rate.',
        'edit_item': 'Edit size — {item}',
        'item_added': 'Added {item} at ₩{price}.',
        'item_saved': 'Saved {item}.',
        'item_activated': '{item} is back on the price list.',
        'item_deactivated': '{item} is hidden from daily entry.',
        'item_deleted': 'Deleted {item} and its rates.',
        'item_in_use': "{item} is used by work records, so it can't be deleted. Deactivate it instead.",
        'confirm_delete_item': 'Delete {item} and its whole rate history?',
        'rate_added': 'New rate for {item}: ₩{price} from {date}.',
        'rate_saved': 'Saved the rate for {item}.',
        'rate_deleted': 'Deleted the {item} rate that started on {date}.',
        'rate_only_one': (
            "This is the only rate for {item}, so it can't be deleted. "
            'Add a replacement first, or deactivate the size.'
        ),
        'confirm_delete_rate': 'Delete this rate? Work already recorded keeps its saved price.',
        'rate_change_note': (
            'Changing a rate never changes work that is already recorded — '
            'each record keeps the price it was saved with.'
        ),
        'err_duplicate_item': '{item} is already on the price list.',
        'err_duplicate_rate_date': 'This size already has a rate starting on that date — edit that one instead.',
        'style_tongpo_desc': 'fully cut and opened out',
        'style_tonghalbok_desc': 'belly slit and gutted',
        'hidden': 'Hidden',
        'no_items': 'Nothing on the price list for this style yet.',

        'err_form': 'Please fix the highlighted fields.',
        'err_required': 'This field is required.',
        'err_number': 'Enter a whole number, e.g. 4500.',
        'err_price_min': 'The price must be at least ₩1.',
        'err_date': 'Enter a valid date.',
        'err_choice': 'Choose one of the options.',
        'err_max_length': 'Too long — at most %(limit_value)d characters.',
        'err_order_range': 'Enter a number from 0 to 32767.',
    },
    'ko': {
        'nav': '손질 작업',
        'module': '생선 손질 수당',
        'hub_intro': (
            '손질 작업자의 작업량과 수당을 기록합니다. 작업자는 로그인하지 않으며, '
            '모든 입력은 관리자가 합니다.'
        ),
        'home': '← 손질 작업 홈',
        'save': '저장',
        'cancel': '취소',
        'edit': '수정',
        'delete': '삭제',
        'activate': '활성화',
        'deactivate': '비활성화',

        'tile_cutters': '작업자',
        'tile_cutters_desc': '작업자 명단 — 추가, 이름 수정, 비활성화.',
        'tile_prices': '단가표',
        'tile_prices_desc': '손질 방식·크기별 박스당 단가와 적용 시작일.',
        'stat_active_cutters': '활성 작업자',
        'stat_price_items': '단가 등록 크기',

        'cutters_title': '작업자',
        'cutters_intro': (
            '작업자는 기록용이며 로그인 계정이 없습니다. 그만둔 작업자는 비활성화하세요. '
            '일일 입력 목록에서는 빠지지만 지난 작업 기록은 그대로 남습니다.'
        ),
        'add_cutter': '작업자 추가',
        'edit_cutter': '작업자 수정 — {name}',
        'name': '이름',
        'note': '메모',
        'note_help': '선택 사항 — 예: 연락처, 조.',
        'active_cutters': '활성 작업자',
        'inactive_cutters': '비활성 작업자',
        'no_cutters': '등록된 작업자가 없습니다. 위에서 첫 작업자를 추가하세요.',
        'cutter_added': '{name} 님을 추가했습니다.',
        'cutter_saved': '{name} 님 정보를 저장했습니다.',
        'cutter_activated': '{name} 님을 다시 활성화했습니다.',
        'cutter_deactivated': '{name} 님을 비활성화했습니다.',
        'cutter_deleted': '{name} 님을 삭제했습니다.',
        'cutter_in_use': '{name} 님은 작업 기록이 있어 삭제할 수 없습니다. 대신 비활성화하세요.',
        'confirm_delete_cutter': '{name} 님을 삭제할까요? 되돌릴 수 없습니다.',
        'err_duplicate_name': '같은 이름의 작업자가 이미 있습니다. 구분할 수 있게 덧붙여 주세요. 예: "김민수 A".',

        'prices_title': '단가표',
        'prices_intro': (
            '수당은 박스 단위로 계산합니다. 단가마다 적용 시작일이 있으며 그날부터 적용됩니다. '
            '단가가 바뀌어도 이미 기록된 작업은 저장 당시의 단가를 그대로 유지합니다.'
        ),
        'style': '손질 방식',
        'size': '크기',
        'size_help': '단가표에 적힌 그대로 — 예: 7, 10~11, 4,5,6.',
        'sort_order': '표시 순서',
        'sort_order_help': '숫자가 작을수록 먼저 표시됩니다. 비워 두면 맨 뒤에 추가됩니다.',
        'unit_price': '박스당 단가 (₩)',
        'effective_from': '적용 시작일',
        'since': '{date}부터',
        'no_current_rate': '오늘 적용되는 단가 없음',
        'upcoming_rate': '{date}부터: ₩{price}',
        'rate_history': '단가 이력',
        'add_rate': '새 단가',
        'add_rate_title': '새 단가 — {item}',
        'edit_rate_title': '단가 수정 — {item}',
        'add_item': '크기 추가',
        'add_item_intro': '단가표에 새 항목을 첫 단가와 함께 추가합니다.',
        'edit_item': '크기 수정 — {item}',
        'item_added': '{item} 항목을 ₩{price}로 추가했습니다.',
        'item_saved': '{item} 항목을 저장했습니다.',
        'item_activated': '{item} 항목을 단가표에 다시 표시합니다.',
        'item_deactivated': '{item} 항목을 일일 입력에서 숨겼습니다.',
        'item_deleted': '{item} 항목과 단가 이력을 삭제했습니다.',
        'item_in_use': '{item} 항목은 작업 기록에 사용되어 삭제할 수 없습니다. 대신 비활성화하세요.',
        'confirm_delete_item': '{item} 항목과 모든 단가 이력을 삭제할까요?',
        'rate_added': '{item} 새 단가: {date}부터 ₩{price}.',
        'rate_saved': '{item} 단가를 저장했습니다.',
        'rate_deleted': '{item}의 {date} 시작 단가를 삭제했습니다.',
        'rate_only_one': (
            '{item}의 유일한 단가라 삭제할 수 없습니다. '
            '새 단가를 먼저 추가하거나 크기를 비활성화하세요.'
        ),
        'confirm_delete_rate': '이 단가를 삭제할까요? 이미 기록된 작업은 저장된 단가를 유지합니다.',
        'rate_change_note': '단가를 바꿔도 이미 기록된 작업은 바뀌지 않습니다. 각 기록은 저장 당시의 단가를 유지합니다.',
        'err_duplicate_item': '{item} 항목은 이미 단가표에 있습니다.',
        'err_duplicate_rate_date': '이 크기에는 같은 날짜에 시작하는 단가가 이미 있습니다. 그 단가를 수정하세요.',
        'style_tongpo_desc': '통째로 펼쳐 손질',
        'style_tonghalbok_desc': '배만 갈라 내장 제거',
        'hidden': '숨김',
        'no_items': '이 손질 방식에는 아직 단가가 없습니다.',

        'err_form': '표시된 항목을 확인해 주세요.',
        'err_required': '필수 입력 항목입니다.',
        'err_number': '숫자를 입력하세요. 예: 4500',
        'err_price_min': '단가는 1원 이상이어야 합니다.',
        'err_date': '올바른 날짜를 입력하세요.',
        'err_choice': '목록에서 선택하세요.',
        'err_max_length': '너무 깁니다 — 최대 %(limit_value)d자.',
        'err_order_range': '0부터 32767 사이의 숫자를 입력하세요.',
    },
}
