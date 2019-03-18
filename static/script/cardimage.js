// preload

$(document).ready(function(){
  $( ".card" ).each(
    function() {
      var mvid = $(this).attr("data-mvid")
      var url = `https://api.scryfall.com/cards/multiverse/${mvid}?format=image`
      $('<img/>')[0].src = url;
    }
  )

  $( ".card" ).hover(
    function() {
      var mvid = $(this).attr("data-mvid")
      var url = `https://api.scryfall.com/cards/multiverse/${mvid}?format=image`
      $('#cardimage').attr('src', url)
    }
  )
});
