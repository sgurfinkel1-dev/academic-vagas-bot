const _mainDatepicker = function(){

    var calendarBookingId = document.getElementById("calendarBookingIdToken");
    var daypickerStandalone = document.getElementById("daypicker");
    // Current date to get the week range
    var currentDate = new Date();
    if (daypickerStandalone !== null) {
        var url_param = _getGenericUrlParam("data");

        if (url_param !== 0) {
            if (_hasDate(url_param)) {
            var d = url_param.split("-");
            var new_date = d[1] + "/" + d[0] + "/" + d[2];
            currentDate = new Date(new_date);
            }
        }
    }

    // Only initialize datepicker if we are on a calendar page
    if (calendarBookingId !== undefined && calendarBookingId !== null) {
        var calendarBookingIdToken = calendarBookingId.dataset.groupId;

        function _fillCalendarBookings(){
            var entries = [];
            $(".entries-list li").each(function() {
                entries.push($(this)[0].innerText);
            });
            return entries;
        };

        var calendarDates = _fillCalendarBookings();
        function _getCalendarDates(){
            calendarDates.map(function(calendarBooking){
                var d = calendarBooking.split("-");
                var c = new Date(d[2], d[1] - 1, d[0]).setHours(0, 0, 0, 0).valueOf();
                calendarDates.push(c);
            });
        };

        // Get calendar dates formatted
        _getCalendarDates();

        // Fill calendar with current dates
        function _fillCurrentCalendars(){
            $("#datepicker-autoridades td[data-handler='selectDay']").each(function() {
                $(this).addClass("ui-has-appointments");
            });
        };

        function _calendarDatepicker(calendarDates){
            console.log('linha 38 - main-datepicker.js');
            $("#datepicker-autoridades").datepicker({
                monthNames: ["JAN", "FEV", "MAR", "ABR", "MAI", "JUN", "JUL", "AGO", "SET", "OUT", "NOV", "DEZ"],
                numberOfMonths: 3,
                stepMonths: 1,
                showCurrentAtPos: 1,
                prevText: "Anterior",
                nextText: "Próximo",
                dateFormat: "dd-mm-yy",
                onSelect: function(dateText, datePicker) {
                // Workaround to resolve this related issue: https://stackoverflow.com/q/16955134/10565216
                console.log('linha 49 - main-datepicker.js');
                datePicker.drawMonth += $("#datepicker-autoridades").datepicker(
                    "option",
                    "showCurrentAtPos"
                );
                if (document.location.pathname.includes("calendar")) {
                    _insertParam("calendar", dateText);
                } else {
                    _insertParam("", "-/calendar/" + dateText);
                }
                },
                beforeShowDay: function calendarDatesHighlight(date) {
                return [calendarDates !== undefined && $.inArray(date.valueOf(), calendarDates) + 1, "", null];
                }
            });

            // Set Locale pt-BR (the js must be on project)
            console.log('linha 66 - main-datepicker.js');
            $("#datepicker-autoridades").datepicker($.datepicker.regional["pt-BR"]);
        };

        // Instantiate calendar
        _calendarDatepicker(calendarDates);

        // Fill calendar every time the page load
        _fillCurrentCalendars();

        // Refill calendars on click
        $(document).on("click",".ui-datepicker-next, .ui-datepicker-prev", function() {
            _fillCurrentCalendars();
        });

        // Get selected date and update calendars
        function _selectedDate(){
            var newDate = new Date(
                _urlParam("calendar")
                .split("-")
                .reverse()
                .join("/")
            ).setHours(0, 0, 0, 0);
            if (calendarDates.includes(newDate.valueOf()) && calendarBookingIdToken) {
                console.log('linha 90 - main-datepicker.js');
                $("#datepicker-autoridades").datepicker("setDate", _urlParam("calendar"));
                _fillCurrentCalendars();
                currentDate = new Date(newDate);
            } else {
                currentDate = new Date(newDate);
            }
        };

        // If has some date selected (on url) we update the calendar
        if (_urlParam("calendar") !== null) {
            if (_hasDate(_urlParam("calendar"))) {
                _selectedDate();
            }
        }

        if (calendarBookingIdToken) {
            daypicker(currentDate, "pt-BR", calendarDates, false);
        }
    }

    // Initialize daypicker with locale in standalone mode
    if (daypickerStandalone !== null) {
        if (daypickerStandalone.dataset.daypicker) {
            daypicker(currentDate, "pt-BR", [], true);
        }
    }

    // Get the weekdays based on middle date and range between the middle date (current)
    function _getWeekDays(date, range){
        var weekDays = [];
        var j = 0;

        for (var i = range * 2; i >= 1; i--) {
            if (i >= range + 1) {
            weekDays.push(_addSubDays(date, i - range, false));
            } else {
            j = j + 1;
            weekDays.push(_addSubDays(date, j, true));
            }
        }
        weekDays.splice(3, 0, date);
        return weekDays;
    };
 
    // Add or subtract days from a given date
    function _addSubDays(date, days, add){
        var result = new Date(date);
        if (add) {
            result.setDate(result.getDate() + days);
        } else {
            result.setDate(result.getDate() - days);
        }
        return result;
    };

    // Create a dynamic daypicker based on a given 'current' date
    function daypicker(currentDate, locale, calendarDates, standalone){
        var weekDays = _getWeekDays(currentDate, 3);
        var options = { weekday: "short" };
        
        weekDays.map(function(monthDay){
            var isSelected = currentDate.valueOf() === monthDay.valueOf() ? "is-selected" : "";
            var hasAppointment = $.inArray(monthDay.setHours(0, 0, 0, 0).valueOf(), calendarDates) + 1 >= 1 ? "has-appointment" : " ";
        
            if (standalone) {
            hasAppointment = "has-appointment";
            }
        
            var date = monthDay.toJSON().slice(0, 10);
        
            // dynamically append on HTML the weekDays based on currentDate
            $(".daypicker").append(
            '<li data-day="' +
                date.split("-").reverse().join("/") +
                '" class="day ' +
                isSelected +
                " " +
                hasAppointment +
                '">' +
                '<div class="daypicker-day">' +
                monthDay.getDate() +
                "</div>" +
                '<div class="daypicker-weekday">' +
                monthDay.toLocaleDateString(locale, options) +
                "</div>" +
                "</li>"
            );
        });
    }
};

// Insert param (date) on click in the url
$(document).on("click", ".has-appointment", function() {
  if ($("#daypicker").attr("data-daypicker")) {
    _insertGenericParam(
      "data",
      $(this)
        .attr("data-day")
        .split("/")
        .join("-")
    );
  } else if (document.location.pathname.includes("calendar")) {
    _insertParam(
      "calendar",
      $(this)
        .attr("data-day")
        .split("/")
        .join("-")
    );
  } else {
    _insertParam(
      "",
      "-/calendar/" +
        $(this)
          .attr("data-day")
          .split("/")
          .join("-")
    );
  }
});

// Insert the key value param on URL
function _insertParam(key, value){
  key = encodeURI(key);
  value = encodeURI(value);
  var kvp = document.location.pathname.replace(/\/$/, "");
  var paths = kvp.split("/");

  if (paths.includes("calendar")) {
    if (_hasDate(_urlParam("calendar"))) {
      paths[paths.length - 1] = value;
    } else {
      if (_urlParam("calendar") === null) {
        paths.push(value);
      } else {
        paths[paths.length - 1] = value;
      }
    }

    kvp = paths.join("/");
    var newUrl = window.location.origin + kvp;

    //this will reload the page, it's likely better to store this until finished
    document.location = newUrl;
  } else {
    paths.push(value);
    kvp = paths.join("/");
    var newUrl = window.location.origin + kvp;

    document.location = newUrl;
  }
};

function _insertGenericParam(key, value){
  key = escape(key);
  value = escape(value);
  var kvp = document.location.search.substr(1).split("&");

  if (kvp == "") {
    document.location.href += "?" + key + "=" + value + "#daypicker";
  } else {
    var i = kvp.length;
    var x;
    while (i--) {
      x = kvp[i].split("=");
      if (x[0] == key) {
        x[1] = value;
        kvp[i] = x.join("=");
        break;
      }
    }
    if (i < 0) {
      kvp[kvp.length] = [key, value].join("=");
    }
    //this will reload the page, it's likely better to store this until finished
    document.location.href =
      document.location.origin +
      document.location.pathname +
      "?" +
      kvp.join("&") +
      "#daypicker";
  }
};

var _hasDate = function(date){
  if (date === null) {
    return false;
  }

  var dateParam = null;
  if (Array.isArray(date)) {
    dateParam = date;
  } else {
    dateParam = date.split("-");
  }
  var month = dateParam[1];
  dateParam[1] = dateParam[0];
  dateParam[0] = month;
  return Date.parse(dateParam.join("/")) ? true : false;
};

// Get url params to update calendar with selected one
var _urlParam = function(name){
  var results = new RegExp("[/]" + name + "([^&#]*)").exec(
    window.location.href
  );

  if (results === null || results === "") {
    return null;
  } else if (
    decodeURI(results[1]).replace(/^\/|\/$/g, "").split("/").length > 1
  ) {
    var newPath = new RegExp(".*[/]" + "calendar" + "?").exec(
      document.location.pathname
    );
    document.location = window.origin + newPath[0];
  }
  return decodeURI(results[1]).replace("/", "") || null;
};

function _getGenericUrlParam(name){
  var results = new RegExp("[?&]" + name + "=([^&#]*)").exec(
    window.location.href
  );
  if (results !== null) {
    return decodeURI(results[1]) || 0;
  }
  return 0;
};

$(function() {
  _mainDatepicker();
});

 Liferay.on("endNavigate", function(event) {
   _mainDatepicker();
 });
